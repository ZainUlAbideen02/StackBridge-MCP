from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    status: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    return LoginResponse(token="jwt-sample-token", status="authenticated")
