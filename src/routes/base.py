from fastapi import APIRouter, Depends
from helpers import Settings, get_settings

base_router = APIRouter(
    prefix="/api/v1",
    tags=["base"]
)

@base_router.get("/")
async def welcome(app_settings: Settings = Depends(get_settings)):
    return {
        "App Name": app_settings.APP_NAME,
        "App Version": app_settings.APP_VERSION,
    }