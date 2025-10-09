from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

def home_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📂 Importa scheda (Excel)", callback_data="import:prompt")
    kb.button(text="🏋️ Avvia Workout", callback_data="workout:start")
    kb.button(text="📊 Visualizza Piano", callback_data="view_plan")
    kb.button(text="📈 Progressi", callback_data="view_progress")
    kb.button(text="🔄 Reset", callback_data="reset:confirm")
    kb.adjust(1)
    return kb.as_markup()

def reset_confirmation_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Conferma Reset", callback_data="reset:execute")
    kb.button(text="❌ Annulla", callback_data="reset:cancel")
    kb.adjust(2)
    return kb.as_markup()
