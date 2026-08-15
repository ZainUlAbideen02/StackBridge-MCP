
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .models import BillingAccount, get_db

router = APIRouter(prefix="/api/v1")


class TeamOut(BaseModel):
    id: str
    name: str


class BillingAccountOut(BaseModel):
    id: str
    userId: str
    plan: str
    balance: float


@router.get("/teams", response_model=list[TeamOut])
def get_teams(db: Session = Depends(get_db)):
    """Fetch all teams."""
    # In a full app, queries teams from DB
    return [{"id": "team_1", "name": "Engineering"}]


@router.get("/users/{user_id}/billing", response_model=BillingAccountOut)
def get_user_billing(user_id: str, db: Session = Depends(get_db)):
    """Fetch billing details for a specific user."""
    billing = db.query(BillingAccount).filter(BillingAccount.user_id == user_id).first()
    if not billing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing account not found"
        )
    return BillingAccountOut(
        id=billing.id,
        userId=billing.user_id,
        plan=billing.plan,
        balance=billing.balance,
    )
