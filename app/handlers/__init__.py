from aiogram import Router
from .start import router as start_router
from .import_plan import router as import_router
from .workout import router as workout_router

def get_routers() -> list[Router]:
    return [start_router, import_router, workout_router]
