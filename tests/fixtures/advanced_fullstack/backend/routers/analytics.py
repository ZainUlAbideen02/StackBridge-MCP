from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class AnalyticsResponse(BaseModel):
    org_id: str
    active_users: int
    page_views: int


@router.get("/analytics/{org_id}", response_model=AnalyticsResponse)
async def get_analytics(org_id: str):
    return AnalyticsResponse(org_id=org_id, active_users=42, page_views=1337)
