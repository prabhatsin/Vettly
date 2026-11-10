import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.offer import CandidateOfferOut, OfferOut
from app.services.candidate_offers import CandidateOfferService, OfferConflict, OfferNotFound
from app.services.status_machine import InvalidTransition

router = APIRouter(prefix="/candidate", tags=["candidate"])
candidate_only = require_role(UserRole.candidate)


@router.get("/offers", response_model=list[CandidateOfferOut])
def my_offers(user: User = Depends(candidate_only), db: Session = Depends(get_db)):
    return CandidateOfferService(db).list_mine(user)


@router.post("/offers/{offer_id}/accept", response_model=OfferOut)
def accept(offer_id: uuid.UUID, user: User = Depends(candidate_only), db: Session = Depends(get_db)):
    try:
        return CandidateOfferService(db).accept(offer_id, user)
    except OfferNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    except (OfferConflict, InvalidTransition) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.post("/offers/{offer_id}/decline", response_model=OfferOut)
def decline(offer_id: uuid.UUID, user: User = Depends(candidate_only), db: Session = Depends(get_db)):
    try:
        return CandidateOfferService(db).decline(offer_id, user)
    except OfferNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    except (OfferConflict, InvalidTransition) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))