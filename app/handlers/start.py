from aiogram import Router, types
from aiogram.filters import Command
from app.db import Base, engine, get_db
from app.models import User
from app.keyboards import home_menu

router = Router()
Base.metadata.create_all(engine)

def ensure_user(tg_user: types.User) -> User:
    db = get_db()
    user = db.get(User, tg_user.id)
    if not user:
        user = User(id=tg_user.id, username=tg_user.username or "")
        db.add(user)
        db.commit()
    db.close()
    return user

@router.message(Command("start"))
async def start_cmd(message: types.Message):
    ensure_user(message.from_user)
    await message.answer(
        "Ciao! 👋 Cosa vuoi fare oggi?",
        reply_markup=home_menu()
    )
