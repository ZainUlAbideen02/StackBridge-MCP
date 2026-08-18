from fastapi import APIRouter, FastAPI
from routers.analytics import router as analytics_router
from routers.auth import router as auth_router

app = FastAPI(title="Advanced Fullstack API")

v2_router = APIRouter(prefix="/api/v2")
v2_router.include_router(analytics_router)
v2_router.include_router(auth_router)

app.include_router(v2_router)
