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

# Piano completo importato (lista di dict)
workout_plan: list[dict] = []

# Sessioni utente: per ogni utente salviamo il sotto-piano scelto e l'indice corrente
# user_sessions[user_id] = {"allenamento": "PUSH", "plan": [...], "idx": 0}
user_sessions: dict[int, dict] = {}


# =========================
# /start e /help
# =========================
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "💪 Benvenuto nel tuo Workout Bot!\n\n"
        "📂 /import_plan – Invia un file Excel con il piano\n"
        "📋 /show_plan – Mostra il piano importato, formattato\n"
        "🏋️ /workout_plan – Avvia l’allenamento scegliendo il blocco (LOWER/PULL/PUSH)\n"
        "❌ /cancel – Annulla la sessione in corso"
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
        # Scarica via Telegram File API (url diretto)
        file = await bot.get_file(message.document.file_id)
        file_path = file.file_path
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

        df = pd.read_excel(file_url)

        expected = {"Allenamento", "Esercizio", "Serie", "Ripetizioni", "Recupero"}
        if not expected.issubset(set(df.columns)):
            return await message.answer(
                "⚠️ Il file non ha le intestazioni richieste.\n"
                "Servono le colonne: Allenamento, Esercizio, Serie, Ripetizioni, Recupero."
            )

        # Normalizza stringhe/valori basilari
        df["Allenamento"] = df["Allenamento"].astype(str).str.strip()
        df["Esercizio"] = df["Esercizio"].astype(str).str.strip()
        # Manteniamo Serie / Ripetizioni / Recupero come testo così supportiamo '≥30''', 'Max', ecc.
        workout_plan = df.to_dict(orient="records")

        # Piccolo riepilogo
        blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
        await message.answer(
            f"✅ Piano importato! Esercizi: {len(workout_plan)}\n"
            f"Blocchi trovati: {', '.join(blocchi)}\n\n"
            "Usa /show_plan per vedere la scheda o /workout_plan per iniziare."
        )
    except Exception as e:
        await message.answer(f"❌ Errore durante l'import: {e}")


# =========================
# Visualizza il piano formattato
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
            # Mostriamo Recupero "as-is" (potrebbe essere 90'', 120'', Max, ecc.)
            rec_txt = str(ex.get("Recupero", "")).strip()
            text += (
                f"   🔹 {ex['Esercizio']} — {ex['Serie']}×{ex['Ripetizioni']}"
                + (f" · rec {rec_txt}" if rec_txt else "")
                + "\n"
            )
        text += "\n"

    await message.answer(text, parse_mode="Markdown")


# =========================
# Allenamento guidato
# =========================
@dp.message(Command("workout_plan"))
async def workout_plan_entry(message: Message):
    """Chiede all'utente quale blocco allenamento vuole eseguire (LOWER/PULL/PUSH ecc.)."""
    if not workout_plan:
        return await message.answer("⚠️ Nessun piano importato. Usa prima /import_plan 📂")

    # Estrai i blocchi unici dall'Excel
    blocchi = sorted(set(r["Allenamento"] for r in workout_plan))
    if not blocchi:
        return await message.answer("⚠️ Il piano è vuoto. Importa un file valido.")

    kb = InlineKeyboardBuilder()
    for b in blocchi:
        kb.button(text=b, callback_data=f"choose_day:{b}")
    kb.adjust(2)

    await message.answer("Scegli l'allenamento che vuoi eseguire oggi:", reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("choose_day:"))
async def choose_day(callback: CallbackQuery):
    """Imposta la sessione utente con il sottopiano del blocco scelto, poi mostra il primo esercizio."""
    day = callback.data.split(":", 1)[1]

    # Filtra solo gli esercizi di quel blocco
    subplan = [r for r in workout_plan if str(r.get("Allenamento", "")).strip() == day]
    if not subplan:
        await callback.answer()
        return await callback.message.answer(f"😬 Nessun esercizio trovato per '{day}'.")

    # Ordine così come è nel file; se vuoi ordinarli diversamente, applica qui un sort

    user_sessions[callback.from_user.id] = {
        "allenamento": day,
        "plan": subplan,
        "idx": 0
    }

    await callback.answer()
    await send_exercise(callback.from_user.id, callback)


async def send_exercise(user_id: int, message_or_callback: Message | CallbackQuery):
    """Mostra l'esercizio corrente della sessione utente, con pulsanti di navigazione."""
    session = user_sessions.get(user_id)
    if not session:
        # Nessuna sessione attiva
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.answer("⚠️ Nessuna sessione attiva. Usa /workout_plan per iniziare.")
            await message_or_callback.answer()
        else:
            await message_or_callback.answer("⚠️ Nessuna sessione attiva. Usa /workout_plan per iniziare.")
        return

    idx = max(0, session["idx"])
    plan = session["plan"]

    if idx >= len(plan):
        # Fine piano
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(
                f"🎉 Allenamento **{session['allenamento']}** completato! Bravo 💪🔥",
                parse_mode="Markdown"
            )
            await message_or_callback.answer()
        else:
            await message_or_callback.answer(f"🎉 Allenamento **{session['allenamento']}** completato! Bravo 💪🔥", parse_mode="Markdown")
        user_sessions.pop(user_id, None)
        return

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
    kb.button(text="✅ Fine", callback_data="nav:end")
    kb.adjust(3)

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "nav:next")
async def nav_next(callback: CallbackQuery):
    session = user_sessions.get(callback.from_user.id)
    if not session:
        await callback.answer()
        return await callback.message.answer("⚠️ Nessuna sessione attiva. Usa /workout_plan.")
    session["idx"] += 1
    await send_exercise(callback.from_user.id, callback)

@dp.callback_query(F.data == "nav:prev")
async def nav_prev(callback: CallbackQuery):
    session = user_sessions.get(callback.from_user.id)
    if not session:
        await callback.answer()
        return await callback.message.answer("⚠️ Nessuna sessione attiva. Usa /workout_plan.")
    session["idx"] = max(0, session["idx"] - 1)
    await send_exercise(callback.from_user.id, callback)

@dp.callback_query(F.data == "nav:end")
async def nav_end(callback: CallbackQuery):
    session = user_sessions.pop(callback.from_user.id, None)
    if session:
        await callback.message.edit_text(
            f"✅ Allenamento **{session['allenamento']}** terminato. Ottimo lavoro! 🔥💪",
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text("✅ Sessione terminata.")
    await callback.answer()


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
