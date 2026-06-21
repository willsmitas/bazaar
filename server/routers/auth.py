from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.models import School, User
from server.dependencies import get_current_user, get_db
from server.email import send_reset_code, send_verification_code
from server.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from server.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    generate_otp,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_OTP_TTL = timedelta(minutes=15)


@router.post("/register", response_model=UserResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create an account and send a verification code to the email address.

    The email domain determines which school's marketplace the user joins; a
    domain with no matching active school is rejected.
    """
    domain = body.email.rsplit("@", 1)[-1].lower()
    school = (
        db.query(School)
        .filter(School.is_active.is_(True), School.email_domains.any(domain))
        .first()
    )
    if not school:
        raise HTTPException(
            status_code=403,
            detail=f"Bazaar isn't available for @{domain} yet — we add schools one at a time.",
        )
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    code = generate_otp()
    user = User(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        school_id=school.school_id,
        university=school.name,   # display name, authoritative from the school
        verification_code=code,
        verification_code_exp=datetime.now(timezone.utc) + _OTP_TTL,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    send_verification_code(user.email, code)
    return user


@router.post("/verify-email", response_model=UserResponse)
def verify_email(
    body:         VerifyEmailRequest,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    """Submit the 6-digit code sent to the user's email address."""
    if current_user.email_verified:
        return current_user

    if not current_user.verification_code:
        raise HTTPException(status_code=400, detail="No pending verification — request a new code")
    if current_user.verification_code != body.code:
        raise HTTPException(status_code=400, detail="Incorrect code")
    if datetime.now(timezone.utc) > current_user.verification_code_exp:
        raise HTTPException(status_code=400, detail="Code has expired — request a new one")

    current_user.email_verified       = True
    current_user.verification_code    = None
    current_user.verification_code_exp = None
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/resend-verification", status_code=200)
def resend_verification(
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    """Issue a fresh verification code and resend it."""
    if current_user.email_verified:
        raise HTTPException(status_code=400, detail="Email is already verified")

    code = generate_otp()
    current_user.verification_code     = code
    current_user.verification_code_exp = datetime.now(timezone.utc) + _OTP_TTL
    db.commit()

    send_verification_code(current_user.email, code)
    return {"message": "Verification code resent"}


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and receive an access token + refresh token."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is suspended or banned")

    user.last_active_at = datetime.now(timezone.utc)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.user_id)),
        refresh_token=create_refresh_token(str(user.user_id)),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new token pair."""
    user_id = decode_refresh_token(body.refresh_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return TokenResponse(
        access_token=create_access_token(str(user.user_id)),
        refresh_token=create_refresh_token(str(user.user_id)),
    )


@router.post("/forgot-password", status_code=200)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send a password-reset code.  Always returns 200 to prevent email enumeration."""
    user = db.query(User).filter(User.email == body.email).first()
    if user and user.is_active:
        code = generate_otp()
        user.password_reset_code     = code
        user.password_reset_code_exp = datetime.now(timezone.utc) + _OTP_TTL
        db.commit()
        send_reset_code(user.email, code)
    return {"message": "If that email is registered, a reset code has been sent"}


@router.post("/reset-password", status_code=200)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Verify the reset code and set a new password."""
    # Use a deliberately vague error to avoid hinting at which field is wrong
    _invalid = HTTPException(status_code=400, detail="Invalid or expired reset code")

    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_reset_code:
        raise _invalid
    if user.password_reset_code != body.code:
        raise _invalid
    if datetime.now(timezone.utc) > user.password_reset_code_exp:
        raise _invalid

    user.password_hash           = hash_password(body.new_password)
    user.password_reset_code     = None
    user.password_reset_code_exp = None
    db.commit()
    return {"message": "Password updated — please log in again"}
