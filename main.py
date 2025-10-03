import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext

# Logging base
logging.basicConfig(level=logging.INFO)

# Carica token da env
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN non trovato nelle variabili d'ambiente!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==============================
# 📋 MENU PRINCIPALE
# ==============================
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Piano Allenamento")],
        [KeyboardButton(text="🏋️ Inizia Allenamento")],
        [KeyboardButton(text="📊 Progressi")],
        [KeyboardButton(text="🔄 Reset")],
    ],
    resize_keyboard=True
)

# ==============================
# 🚀 HANDLERS
# ==============================

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Benvenuto nel Gym Bot 💪\n"
        "Qui puoi gestire i tuoi allenamenti e tracciare i progressi.\n\n"
        "👉 Usa i pulsanti qui sotto per iniziare:",
        reply_markup=main_menu
    )

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "ℹ️ **Comandi disponibili**:\n\n"
        "📋 Piano Allenamento – mostra o carica il piano\n"
        "🏋️ Inizia Allenamento – avvia una sessione guidata\n"
        "📊 Progressi – visualizza i tuoi progressi\n"
        "🔄 Reset – resetta i dati e torna al menu\n\n"
        "Puoi sempre usare il menu in basso 👇",
        reply_markup=main_menu
    )

# Handler per i pulsanti
@dp.message(F.text == "📋 Piano Allenamento")
async def show_plan(message: Message):
    await message.answer("📋 Ecco il tuo piano di allenamento!\n\n(Work in progress: qui possiamo integrare la lettura del piano da file o database)")

@dp.message(F.text == "🏋️ Inizia Allenamento")
async def start_workout(message: Message):
    await message.answer("🏋️ Perfetto! Iniziamo l'allenamento.\n\n(Work in progress: qui partirà la sessione con gli esercizi e il tracking delle serie).")

@dp.message(F.text == "📊 Progressi")
async def show_progress(message: Message):
    await message.answer("📊 Qui vedrai i tuoi progressi.\n\n(Work in progress: possiamo mostrare grafici o log degli allenamenti).")

@dp.message(F.text == "🔄 Reset")
async def reset(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("⚠️ Tutti i dati sono stati resettati.\nTornando al menu principale.", reply_markup=main_menu)

# ==============================
# 🚀 AVVIO BOT
# ==============================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
