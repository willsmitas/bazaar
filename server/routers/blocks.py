from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.models import Block, User
from server.dependencies import get_verified_user, get_db
from server.schemas import BlockedUserResponse, BlockResponse

router = APIRouter(prefix="/users", tags=["blocks"])


@router.post("/{user_id}/block", response_model=BlockResponse, status_code=201)
def block_user(
    user_id:      str,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    if str(current_user.user_id) == user_id:
        raise HTTPException(400, "You can't block yourself")

    target = db.query(User).filter(User.user_id == user_id).first()
    if not target or target.school_id != current_user.school_id:
        raise HTTPException(404, "User not found")

    existing = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.user_id, Block.blocked_id == target.user_id)
        .first()
    )
    if existing:
        raise HTTPException(409, "User is already blocked")

    block = Block(blocker_id=current_user.user_id, blocked_id=target.user_id)
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


@router.delete("/{user_id}/block", status_code=204)
def unblock_user(
    user_id:      str,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    block = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.user_id, Block.blocked_id == user_id)
        .first()
    )
    if not block:
        raise HTTPException(404, "Block not found")
    db.delete(block)
    db.commit()


@router.get("/me/blocks", response_model=List[BlockedUserResponse])
def list_blocks(
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    """Users that the current user has blocked (not the reverse)."""
    blocks = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.user_id)
        .order_by(Block.created_at.desc())
        .all()
    )
    result = []
    for b in blocks:
        target = db.query(User).filter(User.user_id == b.blocked_id).first()
        result.append(BlockedUserResponse(
            block_id=b.block_id,
            blocked_id=b.blocked_id,
            created_at=b.created_at,
            blocked_name=target.full_name if target else None,
        ))
    return result
