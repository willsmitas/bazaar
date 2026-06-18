from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.models import Listing, ListingStatus, ListingType, User
from server.dependencies import get_verified_user, get_db
from server.schemas import CreateListingRequest, ListingResponse, UpdateListingRequest
from server.storage import save_image

router = APIRouter(prefix="/listings", tags=["listings"])


@router.get("", response_model=List[ListingResponse])
def browse(
    q:        Optional[str]         = Query(None, description="Search title and description"),
    category: Optional[str]         = Query(None),
    type:     Optional[ListingType] = Query(None),
    limit:    int                   = Query(50, ge=1, le=100, description="Max results per page"),
    offset:   int                   = Query(0, ge=0, description="Number of results to skip"),
    db:       Session               = Depends(get_db),
):
    query = db.query(Listing).filter(Listing.status == ListingStatus.active)
    if q:
        query = query.filter(
            or_(Listing.title.ilike(f"%{q}%"), Listing.description.ilike(f"%{q}%"))
        )
    if category:
        query = query.filter(Listing.category == category)
    if type:
        query = query.filter(Listing.type == type)
    return query.order_by(Listing.created_at.desc()).offset(offset).limit(limit).all()


@router.post("", response_model=ListingResponse, status_code=201)
def create_listing(
    body:         CreateListingRequest,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    listing = Listing(**body.model_dump(), seller_id=current_user.user_id)
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


# NOTE: this must be declared BEFORE "/{listing_id}", otherwise FastAPI would
# match "/listings/me" against the path-parameter route and treat "me" as an id.
@router.get("/me", response_model=List[ListingResponse])
def my_listings(
    status:       Optional[ListingStatus] = Query(None, description="Filter by status; omit for all"),
    current_user: User                    = Depends(get_verified_user),
    db:           Session                 = Depends(get_db),
):
    """All of the current user's listings (any status), newest first."""
    query = db.query(Listing).filter(Listing.seller_id == current_user.user_id)
    if status:
        query = query.filter(Listing.status == status)
    return query.order_by(Listing.created_at.desc()).all()


@router.get("/{listing_id}", response_model=ListingResponse)
def get_listing(listing_id: str, db: Session = Depends(get_db)):
    listing = _get_or_404(listing_id, db)
    # Increment atomically in SQL (view_count = view_count + 1) so concurrent
    # views don't clobber each other via a read-modify-write race.
    listing.view_count = Listing.view_count + 1
    db.commit()
    db.refresh(listing)
    return listing


@router.put("/{listing_id}", response_model=ListingResponse)
def update_listing(
    listing_id:   str,
    body:         UpdateListingRequest,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    listing = _get_or_404(listing_id, db)
    _assert_owner(listing, current_user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(listing, field, value)
    db.commit()
    db.refresh(listing)
    return listing


@router.delete("/{listing_id}", status_code=204)
def delete_listing(
    listing_id:   str,
    current_user: User    = Depends(get_verified_user),
    db:           Session = Depends(get_db),
):
    listing = _get_or_404(listing_id, db)
    _assert_owner(listing, current_user)
    listing.status = ListingStatus.removed
    db.commit()


@router.post("/{listing_id}/images", response_model=ListingResponse)
async def upload_image(
    listing_id:   str,
    file:         UploadFile = File(...),
    current_user: User       = Depends(get_verified_user),
    db:           Session    = Depends(get_db),
):
    listing = _get_or_404(listing_id, db)
    _assert_owner(listing, current_user)

    url = await save_image(file)
    if not listing.thumbnail_url:
        listing.thumbnail_url = url
    listing.image_urls = (listing.image_urls or []) + [url]

    db.commit()
    db.refresh(listing)
    return listing


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_or_404(listing_id: str, db: Session) -> Listing:
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


def _assert_owner(listing: Listing, user: User) -> None:
    if listing.seller_id != user.user_id:
        raise HTTPException(status_code=403, detail="Not your listing")
