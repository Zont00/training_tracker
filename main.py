import os
import asyncio
import logging
from itertools import groupby

import pandas as pd
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# =========================
# Setup
# =========================
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN mancante. Imposta la variabile d'ambiente.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Piano completo importato
workout_plan: list[dict] = []

# Sessioni utente
# user_sessions[user_id] = {"allenamento": "PUSH", "plan": [...], "idx": 0}
user_sessions: dict[int, dict] = {}

# Log delle serie utente
# user_logs[user_id][allenamento][esercizio] = [{"peso": X, "ripetizioni": Y}, ...]
user_logs: dict[int, dict] = {}


# =========================
# /start e /help
# =========================
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "💪 Benvenuto nel tuo Workout Bot!\n\n"
        "📂 /import_plan – Invia un file Excel con il piano\n"
        "📋 /show_plan – Mostra il piano importato\n"
        "🏋️ /workout_plan – Avvia l’allenamento scegliendo il blocco (LOWER/PULL/PUSH)\n"
        "❌ /cancel – Annulla la sessione\n"
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await start(message)


# =========================
# Import del piano (.xlsx)
# =========================
@dp.message(Command("import_plan"))
async def import_plan(message: Message):
    await message.answer("📂 Inviami un file **Excel (.xlsx)** con le colonne: Allenamento, Esercizio, Serie, Ripetizioni, Recupero.")

@dp.message(F.document)
async def handle_excel(message: Message):
    global workout_plan
    try:
        file = await bot.get_file(message.document.file_id)
        file_path = file.file_path
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

        df = pd.read_excel(file_url)

        expected = {"Allenamento", "Esercizio", "Serie", "Ripetizioni", "Recupero"}
        if not expected.issubset(set(df.columns)):
            return await message.answer("⚠️ Il file deve contenere le colonne: Allenamento, Esercizio, Serie, Ripetizioni, Recupero.")

        df["Allenamento"] = df["Allenamento"].astype(str).str.strip()
        df["Esercizio"] = df["Esercizio"].astype(str).str.strip()
        workout_plan = df.to_dict(orient="records")

        blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
        await message.answer(
            f"✅ Piano importato! Esercizi: {len(workout_plan)}\n"
            f"Blocchi: {', '.join(blocchi)}\n\n"
            "Usa /show_plan per vedere la scheda o /workout_plan per iniziare."
        )
    except Exception as e:
        await message.answer(f"❌ Errore durante l'import: {e}")


# =========================
# Visualizza piano formattato
# =========================
@dp.message(Command("show_plan"))
async def show_plan(message: Message):
    if not workout_plan:
        return await message.answer("⚠️ Nessun piano importato. Usa prima /import_plan 📂")

    text = "📋 **Il tuo piano di allenamento:**\n\n"
    plan_sorted = sorted(workout_plan, key=lambda x: x["Allenamento"])
    for allenamento, esercizi in groupby(plan_sorted, key=lambda x: x["Allenamento"]):
        text += f"🏷️ **{allenamento}**\n"
        for ex in esercizi:
            rec_txt = str(ex.get("Recupero", "")).strip()
            text += f"   🔹 {ex['Esercizio']} — {ex['Serie']}×{ex['Ripetizioni']} (rec {rec_txt})\n"
        text += "\n"

    await message.answer(text, parse_mode="Markdown")


# =========================
# Allenamento guidato
# =========================
@dp.message(Command("workout_plan"))
async def workout_plan_entry(message: Message):
    if not workout_plan:
        return await message.answer("⚠️ Nessun piano importato. Usa prima /import_plan 📂")

    blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
    kb = InlineKeyboardBuilder()
    for b in blocchi:
        kb.button(text=b, callback_data=f"choose_day:{b}")
    kb.adjust(2)

    await message.answer("Scegli l'allenamento che vuoi eseguire oggi:", reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("choose_day:"))
async def choose_day(callback: CallbackQuery):
    day = callback.data.split(":", 1)[1]
    subplan = [r for r in workout_plan if str(r.get("Allenamento", "")) == day]

    user_sessions[callback.from_user.id] = {"allenamento": day, "plan": subplan, "idx": 0}
    user_logs.setdefault(callback.from_user.id, {}).setdefault(day, {})

    await callback.answer()
    await send_exercise(callback.from_user.id, callback)


async def send_exercise(user_id: int, message_or_callback: Message | CallbackQuery):
    session = user_sessions.get(user_id)
    if not session:
        return

    idx = session["idx"]
    plan = session["plan"]

    if idx >= len(plan):
        return await end_workout(user_id, message_or_callback)

    ex = plan[idx]
    rec_txt = str(ex.get("Recupero", "")).strip()
    text = (
        f"🏋️ *{session['allenamento']}* — Esercizio {idx+1}/{len(plan)}\n\n"
        f"📌 {ex['Esercizio']}\n"
        f"📊 Serie: {ex['Serie']} | Ripetizioni: {ex['Ripetizioni']}\n"
        + (f"⏱ Recupero: {rec_txt}" if rec_txt else "")
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="⏮️ Indietro", callback_data="nav:prev")
    kb.button(text="⏭️ Avanti", callback_data="nav:next")
    kb.button(text="➕ Registra serie", callback_data="nav:log")
    kb.button(text="✅ Fine", callback_data="nav:end")
    kb.adjust(2, 2)

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())


# =========================
# Navigazione esercizi
# =========================
@dp.callback_query(F.data == "nav:next")
async def nav_next(callback: CallbackQuery):
    user_sessions[callback.from_user.id]["idx"] += 1
    await send_exercise(callback.from_user.id, callback)

@dp.callback_query(F.data == "nav:prev")
async def nav_prev(callback: CallbackQuery):
    user_sessions[callback.from_user.id]["idx"] = max(0, user_sessions[callback.from_user.id]["idx"] - 1)
    await send_exercise(callback.from_user.id, callback)

@dp.callback_query(F.data == "nav:end")
async def nav_end(callback: CallbackQuery):
    await end_workout(callback.from_user.id, callback)


# =========================
# Logging delle serie
# =========================
@dp.callback_query(F.data == "nav:log")
async def log_series(callback: CallbackQuery):
    session = user_sessions.get(callback.from_user.id)
    if not session:
        return await callback.answer("⚠️ Nessuna sessione attiva.")
    idx = session["idx"]
    exercise = session["plan"][idx]["Esercizio"]

    await callback.message.answer(f"➕ Inserisci i dati per **{exercise}**\nFormato: `peso ripetizioni`\n(Esempio: `50 10`)", parse_mode="Markdown")
    await callback.answer()

    # Salviamo che l'utente deve loggare
    session["awaiting_log"] = True


@dp.message()
async def capture_log(message: Message):
    session = user_sessions.get(message.from_user.id)
    if not session or not session.get("awaiting_log"):
        return

    try:
        peso, reps = message.text.strip().split()
        log_entry = {"peso": peso, "ripetizioni": reps}
        allenamento = session["allenamento"]
        idx = session["idx"]
        exercise = session["plan"][idx]["Esercizio"]

        user_logs[message.from_user.id][allenamento].setdefault(exercise, []).append(log_entry)
        session["awaiting_log"] = False

        await message.answer(f"✅ Serie registrata: {peso}kg x {reps} reps per {exercise}")
    except Exception:
        await message.answer("⚠️ Formato non valido. Usa ad esempio: `50 10`")


# =========================
# Fine allenamento
# =========================
async def end_workout(user_id: int, message_or_callback: Message | CallbackQuery):
    session = user_sessions.pop(user_id, None)
    if not session:
        return

    allenamento = session["allenamento"]
    logs = user_logs.get(user_id, {}).get(allenamento, {})

    text = f"🎉 Allenamento **{allenamento}** terminato!\n\n"
    if logs:
        text += "📊 Ecco le tue serie registrate:\n"
        for ex, series in logs.items():
            text += f"\n🔹 {ex}\n"
            for s in series:
                text += f"   - {s['peso']}kg x {s['ripetizioni']} reps\n"
    else:
        text += "Nessuna serie registrata."

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, parse_mode="Markdown")
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, parse_mode="Markdown")


# =========================
# Cancel
# =========================
@dp.message(Command("cancel"))
async def cancel_cmd(message: Message):
    user_sessions.pop(message.from_user.id, None)
    await message.answer("❌ Sessione annullata. Puoi riavviare con /workout_plan.")


# =========================
# Entry point
# =========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
