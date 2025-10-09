import io, json
import pandas as pd
from datetime import datetime, timedelta
from aiogram import Router, F, types
from aiogram.filters import Command
from app.db import get_db
from app.models import User, WorkoutLog
from app.utils.plan_parser import parse_plan_from_df

router = Router()

def _get_user(db, tg_user: types.User) -> User:
    user = db.get(User, tg_user.id)
    if not user:
        user = User(id=tg_user.id, username=tg_user.username or "")
        db.add(user)
        db.commit()
    return user

@router.message(Command("import_plan"))
async def import_plan_cmd(message: types.Message):
    await message.answer("📂 Inviami un file <b>.xlsx</b> con le colonne: <b>Allenamento, Esercizio, Serie, Ripetizioni, Recupero</b>.")

@router.callback_query(F.data == "import:prompt")
async def import_prompt(cb: types.CallbackQuery):
    await cb.message.answer("📂 Inviami un file <b>.xlsx</b> con le colonne: <b>Allenamento, Esercizio, Serie, Ripetizioni, Recupero</b>.")
    await cb.answer()


@router.message(F.document)
async def handle_excel(message: types.Message):
    if not message.document.file_name.lower().endswith(".xlsx"):
        return await message.answer("⚠️ Il file deve essere un <b>.xlsx</b> (Excel).")

    db = get_db()
    user = _get_user(db, message.from_user)
    try:
        file = await message.bot.get_file(message.document.file_id)
        buf = io.BytesIO()
        await message.bot.download_file(file.file_path, destination=buf)
        buf.seek(0)

        df = pd.read_excel(buf)
        plan = parse_plan_from_df(df)

        user.training_plan = json.dumps(plan, ensure_ascii=False)
        user.current_day = None
        user.exercise_idx = 0
        user.set_idx = 0
        db.commit()

        await message.answer(
            "✅ Scheda importata con successo!\n"
            f"Allenamenti trovati: <b>{', '.join(plan.keys())}</b>\n"
            "Usa /workout per iniziare o /progress per vedere i progressi."
        )
    except Exception as e:
        await message.answer(f"❌ Errore nell'importazione: <code>{e}</code>")
    finally:
        db.close()
