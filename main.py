import os
import asyncio
import logging
import pandas as pd
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Piano allenamento e sessioni utente
workout_plan: list[dict] = []
user_sessions: dict[int, dict] = {}
user_logs: dict[int, dict] = {}  # storico

# ========================
# START
# ========================
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "💪 Benvenuto nel Workout Bot!\n\n"
        "📂 /import_plan – carica il piano in Excel\n"
        "🏋️ /workout – scegli e avvia un allenamento\n"
        "❌ /cancel – annulla"
    )

# ========================
# IMPORT
# ========================
@dp.message(Command("import_plan"))
async def import_plan(message: Message):
    await message.answer("📂 Inviami un file Excel con colonne: Allenamento, Esercizio, Serie, Ripetizioni, Recupero.")

@dp.message(F.document)
async def handle_excel(message: Message):
    global workout_plan
    try:
        file = await bot.get_file(message.document.file_id)
        url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
        df = pd.read_excel(url)

        workout_plan = df.to_dict(orient="records")
        blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
        await message.answer(f"✅ Piano caricato! Blocchi disponibili: {', '.join(blocchi)}\nUsa /workout per iniziare.")
    except Exception as e:
        await message.answer(f"❌ Errore: {e}")

# ========================
# AVVIO WORKOUT
# ========================
@dp.message(Command("workout"))
async def workout(message: Message):
    if not workout_plan:
        return await message.answer("⚠️ Nessun piano importato.")
    blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
    await message.answer("Scegli un allenamento:\n" + "\n".join([f"- {b}" for b in blocchi]))

    # salva scelta in sessione (in attesa risposta utente)
    user_sessions[message.from_user.id] = {"awaiting_day": True}

@dp.message()
async def choose_day_or_log(message: Message):
    user_id = message.from_user.id
    session = user_sessions.get(user_id)

    if not session:
        return

    # ========================
    # 1) Scelta allenamento
    # ========================
    if session.get("awaiting_day"):
        day = message.text.strip()
        subplan = [r for r in workout_plan if r["Allenamento"].lower() == day.lower()]
        if not subplan:
            return await message.answer("⚠️ Allenamento non trovato. Riprova.")

        # imposta sessione
        user_sessions[user_id] = {
            "allenamento": day,
            "plan": subplan,
            "exercise_idx": 0,
            "set_idx": 0,
            "logs": {}
        }
        await send_next_set(user_id, message)
        return

    # ========================
    # 2) Logging peso/reps
    # ========================
    if "expecting_input" in session and session["expecting_input"]:
        try:
            peso, reps = message.text.strip().split()
            peso, reps = int(peso), int(reps)
        except Exception:
            return await message.answer("⚠️ Formato non valido. Usa: `peso reps` (es. `50 10`).")

        ex = session["plan"][session["exercise_idx"]]["Esercizio"]
        session["logs"].setdefault(ex, []).append({"peso": peso, "reps": reps})
        session["set_idx"] += 1
        session["expecting_input"] = False

        await send_next_set(user_id, message)

# ========================
# Avanzamento esercizi/serie
# ========================
async def send_next_set(user_id: int, message: Message):
    session = user_sessions[user_id]
    plan = session["plan"]

    if session["exercise_idx"] >= len(plan):
        return await end_workout(user_id, message)

    ex = plan[session["exercise_idx"]]
    serie_tot = int(ex["Serie"])

    if session["set_idx"] < serie_tot:
        session["expecting_input"] = True
        await message.answer(
            f"🏋️ {ex['Esercizio']} — Serie {session['set_idx']+1}/{serie_tot}\n"
            f"📊 Target: {ex['Ripetizioni']} reps | Recupero: {ex.get('Recupero','')}\n"
            f"Inserisci: `peso reps`"
        )
    else:
        session["exercise_idx"] += 1
        session["set_idx"] = 0
        await send_next_set(user_id, message)

# ========================
# Fine allenamento + confronto
# ========================
async def end_workout(user_id: int, message: Message):
    session = user_sessions.pop(user_id, None)
    if not session:
        return

    allenamento = session["allenamento"]
    logs = session["logs"]
    storico = user_logs.setdefault(user_id, {}).setdefault(allenamento, [])

    # confronto con ultimo allenamento
    confronto_txt = ""
    if storico:
        confronto_txt = "\n📈 Confronto con la volta precedente:\n"
        last = storico[-1]
        for ex, serie in logs.items():
            confronto_txt += f"\n🔹 {ex}\n"
            for i, s in enumerate(serie):
                if ex in last and i < len(last[ex]):
                    prev = last[ex][i]
                    trend = "➡️"
                    if s["peso"] > prev["peso"] or s["reps"] > prev["reps"]:
                        trend = "🔼"
                    elif s["peso"] < prev["peso"] or s["reps"] < prev["reps"]:
                        trend = "🔽"
                    confronto_txt += f"   {s['peso']}kg x {s['reps']} ({trend} vs {prev['peso']}kg x {prev['reps']})\n"
                else:
                    confronto_txt += f"   {s['peso']}kg x {s['reps']} (nuova serie)\n"

    storico.append(logs)

    text = f"🎉 Allenamento **{allenamento}** completato!\n"
    for ex, serie in logs.items():
        text += f"\n🔹 {ex}\n"
        for s in serie:
            text += f"   - {s['peso']}kg x {s['reps']}\n"

    text += confronto_txt
    await message.answer(text)

# ========================
# CANCEL
# ========================
@dp.message(Command("cancel"))
async def cancel(message: Message):
    user_sessions.pop(message.from_user.id, None)
    await message.answer("❌ Sessione annullata.")

# ========================
# RUN
# ========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
