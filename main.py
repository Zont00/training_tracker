import logging
import pandas as pd
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
import asyncio
import os

# --- Logging ---
logging.basicConfig(level=logging.INFO)

# --- Variabili globali ---
TOKEN = os.getenv("BOT_TOKEN")  # Ricorda di settare BOT_TOKEN su Railway
bot = Bot(token=TOKEN)
dp = Dispatcher()

workout_plan = []  # qui verrà salvato il piano importato


# --- Start ---
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "💪 Benvenuto nel tuo Workout Bot!\n\n"
        "Comandi disponibili:\n"
        "📂 /import_plan - Importa un file Excel con il piano\n"
        "📋 /show_plan - Mostra il piano importato\n"
        "🏋️ /workout_plan - Avvia la sessione guidata\n"
    )


# --- Import del piano ---
@dp.message(Command("import_plan"))
async def import_plan(message: Message):
    await message.answer("📂 Inviami un file Excel con il piano di allenamento.")


# --- Ricezione file Excel ---
@dp.message(F.document)
async def handle_file(message: Message):
    global workout_plan
    file = await bot.get_file(message.document.file_id)
    file_path = file.file_path
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

    try:
        df = pd.read_excel(file_url)
        workout_plan = df.to_dict(orient="records")
        await message.answer("✅ Piano importato con successo! Usa /show_plan per visualizzarlo.")
    except Exception as e:
        await message.answer(f"❌ Errore nell'importazione del file: {e}")


# --- Mostra piano formattato ---
@dp.message(Command("show_plan"))
async def show_plan(message: Message):
    global workout_plan

    if not workout_plan:
        await message.answer("⚠️ Nessun piano importato. Usa prima /import_plan 📂")
        return

    text = "📋 **Il tuo piano di allenamento:**\n\n"

    # Raggruppiamo per Allenamento
    from itertools import groupby
    workout_plan_sorted = sorted(workout_plan, key=lambda x: x["Allenamento"])
    for allenamento, esercizi in groupby(workout_plan_sorted, key=lambda x: x["Allenamento"]):
        text += f"🏋️ Allenamento **{allenamento}**\n"
        for ex in esercizi:
            text += f"   🔹 {ex['Esercizio']} — {ex['Serie']}x{ex['Ripetizioni']} (Recupero: {ex['Recupero']} sec)\n"
        text += "\n"

    await message.answer(text, parse_mode="Markdown")


# --- Workout guidato ---
@dp.message(Command("workout_plan"))
async def workout_plan_session(message: Message):
    global workout_plan
    if not workout_plan:
        await message.answer("⚠️ Nessun piano importato. Usa prima /import_plan 📂")
        return

    await message.answer("🚀 Avvio sessione allenamento...\n")
    for exercise in workout_plan:
        text = (
            f"🏋️ Esercizio: *{exercise['Esercizio']}*\n"
            f"📊 Serie: {exercise['Serie']} | Ripetizioni: {exercise['Ripetizioni']}\n"
            f"⏱ Recupero: {exercise['Recupero']} sec"
        )
        await message.answer(text, parse_mode="Markdown")


# --- Main ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())