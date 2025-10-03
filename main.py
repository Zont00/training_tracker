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
user_sessions: dict[int, dict] = {}

# Log delle serie utente con storico
# user_logs[user_id][allenamento] = [{"date": ..., "logs": {exercise: [serie...]}}]
user_logs: dict[int, dict] = {}


# =========================
# /start
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


# =========================
# Import Excel
# =========================
@dp.message(Command("import_plan"))
async def import_plan(message: Message):
    await message.answer("📂 Inviami un file **Excel (.xlsx)** con: Allenamento, Esercizio, Serie, Ripetizioni, Recupero.")

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
            return await message.answer("⚠️ Il file deve avere: Allenamento, Esercizio, Serie, Ripetizioni, Recupero.")

        df["Allenamento"] = df["Allenamento"].astype(str).str.strip()
        df["Esercizio"] = df["Esercizio"].astype(str).str.strip()
        workout_plan = df.to_dict(orient="records")

        blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
        await message.answer(f"✅ Piano importato! Blocchi: {', '.join(blocchi)}\nUsa /show_plan o /workout_plan.")
    except Exception as e:
        await message.answer(f"❌ Errore durante import: {e}")


# =========================
# Mostra piano
# =========================
@dp.message(Command("show_plan"))
async def show_plan(message: Message):
    if not workout_plan:
        return await message.answer("⚠️ Nessun piano importato.")

    text = "📋 **Piano di allenamento:**\n\n"
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
        return await message.answer("⚠️ Nessun piano importato.")

    blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
    kb = InlineKeyboardBuilder()
    for b in blocchi:
        kb.button(text=b, callback_data=f"choose_day:{b}")
    kb.adjust(2)
    await message.answer("Scegli l'allenamento di oggi:", reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("choose_day:"))
async def choose_day(callback: CallbackQuery):
    day = callback.data.split(":", 1)[1]
    subplan = [r for r in workout_plan if r["Allenamento"] == day]

    user_sessions[callback.from_user.id] = {"allenamento": day, "plan": subplan, "idx": 0}
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
# Navigazione
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
# Logging serie
# =========================
@dp.callback_query(F.data == "nav:log")
async def log_series(callback: CallbackQuery):
    session = user_sessions.get(callback.from_user.id)
    if not session:
        return await callback.answer("⚠️ Nessuna sessione attiva.")
    idx = session["idx"]
    exercise = session["plan"][idx]["Esercizio"]

    await callback.message.answer(f"➕ Inserisci i dati per **{exercise}**\nFormato: `peso ripetizioni`\nEsempio: `50 10`", parse_mode="Markdown")
    session["awaiting_log"] = True
    await callback.answer()


@dp.message()
async def capture_log(message: Message):
    session = user_sessions.get(message.from_user.id)
    if not session or not session.get("awaiting_log"):
        return

    try:
        peso, reps = message.text.strip().split()
        log_entry = {"peso": int(peso), "ripetizioni": int(reps)}
        idx = session["idx"]
        exercise = session["plan"][idx]["Esercizio"]
        allenamento = session["allenamento"]

        # Salva log corrente nella sessione
        logs = session.setdefault("logs", {})
        logs.setdefault(exercise, []).append(log_entry)

        session["awaiting_log"] = False
        await message.answer(f"✅ Serie registrata: {peso}kg x {reps} reps per {exercise}")
    except Exception:
        await message.answer("⚠️ Formato non valido. Usa ad esempio: `50 10`")


# =========================
# Fine allenamento con confronto
# =========================
async def end_workout(user_id: int, message_or_callback: Message | CallbackQuery):
    session = user_sessions.pop(user_id, None)
    if not session:
        return

    allenamento = session["allenamento"]
    logs = session.get("logs", {})

    # Recupera storico passato
    storico = user_logs.setdefault(user_id, {}).setdefault(allenamento, [])
    confronto_txt = ""
    if storico:
        confronto_txt = "\n📈 Confronto con la scorsa volta:\n"
        last_logs = storico[-1]["logs"]
        for ex, serie_correnti in logs.items():
            if ex in last_logs:
                confronto_txt += f"\n🔹 {ex}\n"
                for i, s in enumerate(serie_correnti):
                    if i < len(last_logs[ex]):
                        prev = last_logs[ex][i]
                        trend = "➡️"
                        if s["peso"] > prev["peso"] or s["ripetizioni"] > prev["ripetizioni"]:
                            trend = "🔼"
                        elif s["peso"] < prev["peso"] or s["ripetizioni"] < prev["ripetizioni"]:
                            trend = "🔽"
                        confronto_txt += f"   {s['peso']}kg x {s['ripetizioni']} reps ({trend} vs {prev['peso']}kg x {prev['ripetizioni']})\n"
                    else:
                        confronto_txt += f"   {s['peso']}kg x {s['ripetizioni']} reps (nuova serie)\n"

    # Salva la sessione nello storico
    storico.append({"logs": logs})

    # Report finale
    text = f"🎉 Allenamento **{allenamento}** terminato!\n\n"
    if logs:
        text += "📊 Serie registrate:\n"
        for ex, series in logs.items():
            text += f"\n🔹 {ex}\n"
            for s in series:
                text += f"   - {s['peso']}kg x {s['ripetizioni']} reps\n"
    else:
        text += "Nessuna serie registrata."

    text += confronto_txt

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
    await message.answer("❌ Sessione annullata.")


# =========================
# Entry point
# =========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
