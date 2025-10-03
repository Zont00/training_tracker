
import os
import asyncio
import re
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# 🔐 Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ====================
# Config
# ====================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Please set BOT_TOKEN environment variable (see .env.example).")

DB_PATH = os.getenv("DB_PATH", "gymbot.db")

router = Router()

# ====================
# Database helpers
# ====================

CREATE_TABLES_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER UNIQUE NOT NULL,
  unit TEXT NOT NULL DEFAULT 'kg',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exercises (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  day_label TEXT NOT NULL,
  sets INTEGER NOT NULL,
  reps_min INTEGER NOT NULL,
  reps_max INTEGER NOT NULL,
  order_idx INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS workouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  date TEXT NOT NULL,
  day_label TEXT NOT NULL,
  notes TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workout_id INTEGER NOT NULL,
  exercise_id INTEGER NOT NULL,
  set_idx INTEGER NOT NULL,
  weight REAL NOT NULL,
  reps INTEGER NOT NULL,
  ts TEXT NOT NULL,
  FOREIGN KEY (workout_id) REFERENCES workouts(id),
  FOREIGN KEY (exercise_id) REFERENCES exercises(id)
);
"""

DEFAULT_PLAN = {
    "Push": [
        {"name": "Chest Press Orizzontale", "sets": 3, "reps_min": 6, "reps_max": 10},
        {"name": "Alzate Laterali al Cavo", "sets": 3, "reps_min": 8, "reps_max": 12},
    ],
    "Pull": [
        {"name": "Trazioni Presa Prona", "sets": 3, "reps_min": 6, "reps_max": 10},
        {"name": "Rematore Multipower", "sets": 3, "reps_min": 6, "reps_max": 10},
    ],
    "Legs": [
        {"name": "Leg Press (Full ROM)", "sets": 3, "reps_min": 6, "reps_max": 10},
        {"name": "Leg Curl da seduto", "sets": 3, "reps_min": 6, "reps_max": 10},
        {"name": "Calf Machine", "sets": 2, "reps_min": 12, "reps_max": 16},
    ]
}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES_SQL)
        await db.commit()

async def get_or_create_user(telegram_id: int) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
        if row:
            return dict(row)
        created_at = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO users (telegram_id, unit, created_at) VALUES (?, ?, ?)",
            (telegram_id, "kg", created_at)
        )
        await db.commit()
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
        return dict(row)

async def set_user_unit(user_id: int, unit: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET unit = ? WHERE id = ?", (unit, user_id))
        await db.commit()

async def plan_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM exercises WHERE user_id = ?", (user_id,)) as cur:
            cnt = (await cur.fetchone())[0]
    return cnt > 0

async def insert_default_plan(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        order_idx = 0
        for day, items in DEFAULT_PLAN.items():
            for it in items:
                await db.execute(
                    """INSERT INTO exercises (user_id, name, day_label, sets, reps_min, reps_max, order_idx)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, it["name"], day, it["sets"], it["reps_min"], it["reps_max"], order_idx)
                )
                order_idx += 1
        await db.commit()

async def get_day_labels(user_id: int) -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT DISTINCT day_label FROM exercises WHERE user_id = ? ORDER BY day_label", (user_id,)) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]

async def get_exercises_for_day(user_id: int, day_label: str) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM exercises
               WHERE user_id = ? AND day_label = ?
               ORDER BY order_idx ASC""",
            (user_id, day_label)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]

async def create_workout(user_id: int, day_label: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        date = datetime.utcnow().isoformat()
        await db.execute("INSERT INTO workouts (user_id, date, day_label, notes) VALUES (?, ?, ?, NULL)", (user_id, date, day_label))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            workout_id = (await cur.fetchone())[0]
    return int(workout_id)

async def get_last_performance(user_id: int, exercise_id: int) -> Optional[Tuple[float, int]]:
    """Return (weight, reps) from the most recent set of this exercise for the user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
        SELECT s.weight, s.reps
        FROM sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE w.user_id = ? AND s.exercise_id = ?
        ORDER BY s.ts DESC
        LIMIT 1
        """
        async with db.execute(query, (user_id, exercise_id)) as cur:
            row = await cur.fetchone()
            if row:
                return (row["weight"], row["reps"])
    return None

async def insert_set(workout_id: int, exercise_id: int, set_idx: int, weight: float, reps: int):
    async with aiosqlite.connect(DB_PATH) as db:
        ts = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO sets (workout_id, exercise_id, set_idx, weight, reps, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (workout_id, exercise_id, set_idx, weight, reps, ts)
        )
        await db.commit()

# --- Reset helpers ---
async def delete_user_all_data(user_id: int):
    """Delete sets, workouts, exercises and user row for a given user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""DELETE FROM sets WHERE workout_id IN (SELECT id FROM workouts WHERE user_id = ?)""", (user_id,))
        await db.execute("""DELETE FROM workouts WHERE user_id = ?""", (user_id,))
        await db.execute("""DELETE FROM exercises WHERE user_id = ?""", (user_id,))
        await db.execute("""DELETE FROM users WHERE id = ?""", (user_id,))
        await db.commit()

async def delete_user_plan_only(user_id: int):
    """Delete only exercises (plan) for the user; keep user/workouts/sets intact."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""DELETE FROM exercises WHERE user_id = ?""", (user_id,))
        await db.commit()

# ====================
# FSM States
# ====================

class OnboardState(StatesGroup):
    choosing_unit = State()

class WorkoutState(StatesGroup):
    choosing_day = State()
    entering_set = State()

# ====================
# Keyboards
# ====================

def unit_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="kg")], [KeyboardButton(text="lbs")]],
        resize_keyboard=True, one_time_keyboard=True
    )

def day_inline_kb(days: List[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=d, callback_data=f"day:{d}")] for d in days]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def confirm_reset_kb(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Conferma", callback_data=f"confirm_reset:{kind}")],
        [InlineKeyboardButton(text="❌ Annulla", callback_data="cancel_reset")]
    ])

# ====================
# Handlers
# ====================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    if not await plan_exists(user["id"]):
        await message.answer(
            "Ciao! 👋 Impostiamo il bot per tracciare gli allenamenti.\n"
            "Per iniziare, scegli l'unità di misura per i carichi:",
            reply_markup=unit_kb()
        )
        await state.set_state(OnboardState.choosing_unit)
    else:
        await message.answer("Bentornato! Usa /workout per iniziare una sessione.")

@router.message(OnboardState.choosing_unit, F.text.lower().in_({"kg", "lbs"}))
async def set_unit(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    chosen = message.text.lower()
    await set_user_unit(user["id"], chosen)
    await insert_default_plan(user["id"])
    await message.answer(
        f"Perfetto! Unità impostata su **{chosen}** e piano base creato (Push/Pull/Legs). 💪\n"
        "Quando vuoi, scrivi /workout per iniziare una sessione.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True)
    )
    await state.clear()

@router.message(OnboardState.choosing_unit)
async def invalid_unit(message: Message):
    await message.reply("Per favore scegli 'kg' o 'lbs' usando i bottoni.")

@router.message(Command("workout"))
async def cmd_workout(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id)
    days = await get_day_labels(user["id"])
    if not days:
        await message.answer("Non ho trovato un piano attivo. Esegui /start per creare il piano base.")
        return
    await message.answer("Che giorno alleni oggi?", reply_markup=day_inline_kb(days))
    await state.set_state(WorkoutState.choosing_day)

@router.callback_query(WorkoutState.choosing_day, F.data.startswith("day:"))
async def choose_day(callback: CallbackQuery, state: FSMContext):
    day_label = callback.data.split(":", 1)[1]
    user = await get_or_create_user(callback.from_user.id)
    exercises = await get_exercises_for_day(user["id"], day_label)
    if not exercises:
        await callback.message.answer("Nessun esercizio configurato per questo giorno.")
        await callback.answer()
        return

    workout_id = await create_workout(user["id"], day_label)

    await state.update_data(
        workout_id=workout_id,
        day_label=day_label,
        exercises=exercises,
        ex_idx=0,
        set_idx=1
    )
    await callback.message.answer(f"Ok, iniziamo il giorno **{day_label}**. 🔥")
    await callback.answer()
    await state.set_state(WorkoutState.entering_set)
    await prompt_next_set(callback.message, state)

async def prompt_next_set(message: Message, state: FSMContext):
    data = await state.get_data()
    exercises: List[Dict[str, Any]] = data["exercises"]
    ex_idx = data["ex_idx"]
    set_idx = data["set_idx"]

    if ex_idx >= len(exercises):
        await message.answer("Allenamento completato! ✅\nUsa /workout quando vuoi iniziare un'altra sessione.")
        await state.clear()
        return

    current_ex = exercises[ex_idx]
    if set_idx > current_ex["sets"]:
        await state.update_data(ex_idx=ex_idx + 1, set_idx=1)
        return await prompt_next_set(message, state)

    user = await get_or_create_user(message.from_user.id)
    last = await get_last_performance(user["id"], current_ex["id"])
    hint = f"Ultima volta: {last[0]} × {last[1]}" if last else "Nessun dato precedente"
    rep_range = f'{current_ex["reps_min"]}-{current_ex["reps_max"]}'

    await message.answer(
        f"**{current_ex['name']}** — Serie {set_idx}/{current_ex['sets']}  \n"
        f"Target reps: {rep_range}  \n"
        f"{hint}  \n\n"
        "Invia *peso e reps* separati da spazio. Esempio: `62.5 8`  \n"
        "Oppure scrivi `skip` per saltare questa serie.",
        parse_mode="Markdown"
    )

@router.message(WorkoutState.entering_set, F.text & ~F.text.startswith("/"))
async def handle_set_input(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data or "exercises" not in data:
        return

    text = (message.text or "").strip().lower()
    if text == "skip":
        return await advance_set(message, state, skipped=True)

    parts = text.split()
    if len(parts) != 2:
        await state.set_state(WorkoutState.entering_set)
        return await message.reply("Formato non valido. Invia ad esempio: `62.5 8` oppure `skip`.", parse_mode="Markdown")

    try:
        weight = float(parts[0].replace(",", "."))
        reps = int(parts[1])
    except ValueError:
        await state.set_state(WorkoutState.entering_set)
        return await message.reply("Non riesco a leggere i numeri. Prova così: `62.5 8`.", parse_mode="Markdown")

    await advance_set(message, state, weight=weight, reps=reps)

async def advance_set(message: Message, state: FSMContext, skipped: bool = False, weight: float = 0.0, reps: int = 0):
    data = await state.get_data()
    exercises: List[Dict[str, Any]] = data["exercises"]
    ex_idx = data["ex_idx"]
    set_idx = data["set_idx"]
    workout_id = data["workout_id"]

    current_ex = exercises[ex_idx]

    if not skipped:
        await insert_set(workout_id, current_ex["id"], set_idx, weight, reps)
        await message.answer(f"Registrato: {current_ex['name']} — {weight} × {reps} ✅")

    set_idx += 1
    await state.update_data(set_idx=set_idx)
    await state.set_state(WorkoutState.entering_set)
    await prompt_next_set(message, state)

@router.message(WorkoutState.choosing_day)
async def ignore_text_during_day_choice(message: Message):
    await message.reply("Scegli il giorno dai bottoni sopra.")

# ====================
# Reset Commands
# ====================

@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    """Wipes ALL your data, including user row. You'll need to /start again."""
    await message.answer(
        "⚠️ *Attenzione*: questo cancellerà *tutti* i tuoi dati (piano, allenamenti, serie e profilo). "
        "Vorresti procedere?",
        reply_markup=confirm_reset_kb("all"),
        parse_mode="Markdown"
    )

@router.message(Command("reset_plan"))
async def cmd_reset_plan(message: Message, state: FSMContext):
    """Deletes the plan and recreates the default Push/Pull/Legs plan."""
    await message.answer(
        "Questa azione *cancellerà e ricreerà* il tuo piano esercizi (Push/Pull/Legs). "
        "I dati degli allenamenti rimarranno. Procedere?",
        reply_markup=confirm_reset_kb("plan"),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "cancel_reset")
async def cancel_reset(callback: CallbackQuery):
    await callback.message.edit_text("Annullato. Nessuna modifica ai dati. ✅")
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_reset:"))
async def confirm_reset(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(":", 1)[1]
    user = await get_or_create_user(callback.from_user.id)

    if kind == "all":
        await delete_user_all_data(user["id"])
        await callback.message.edit_text("✅ Tutti i tuoi dati sono stati cancellati. Esegui /start per ripartire da zero.")
        await state.clear()
    elif kind == "plan":
        await delete_user_plan_only(user["id"])
        await insert_default_plan(user["id"])
        await callback.message.edit_text("✅ Piano ricreato con il set base Push/Pull/Legs. Puoi usare /workout.")

    await callback.answer()


# ====================
# Migrations (add columns if missing)
# ====================

async def ensure_migrations():
    async with aiosqlite.connect(DB_PATH) as db:
        # Check columns for exercises
        async with db.execute("PRAGMA table_info(exercises)") as cur:
            cols = [row[1] for row in await cur.fetchall()]
        to_add = []
        if "rest_sec" not in cols:
            to_add.append("ALTER TABLE exercises ADD COLUMN rest_sec INTEGER NULL")
        if "reps_text" not in cols:
            to_add.append("ALTER TABLE exercises ADD COLUMN reps_text TEXT NULL")
        for sql in to_add:
            await db.execute(sql)
        if to_add:
            await db.commit()

# ====================
# Import plan (Excel/CSV)
# ====================

class ImportState(StatesGroup):
    waiting_file = State()

HEADER_MAP = {
    "allenamento": "day_label",
    "esercizio": "name",
    "serie": "sets",
    "ripetizioni": "reps",
    "recupero": "rest"
}

DAY_NORMALIZE = {
    "LOWER": "Legs",
    "PULL": "Pull",
    "PUSH": "Push"
}

def parse_rest_to_seconds(s: str) -> int | None:
    if not s:
        return None
    # extract first integer number as seconds (e.g., 90'')
    m = re.search(r'(\d+)', s)
    if not m:
        return None
    return int(m.group(1))

def parse_reps(s: str) -> tuple[int | None, int | None, str | None]:
    """Return (reps_min, reps_max, reps_text). Keep text if non-numeric or contains special notes."""
    if not s:
        return (None, None, None)
    # detect patterns like "6-9", "7–10", "10-15"
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)', s)
    if m:
        return (int(m.group(1)), int(m.group(2)), None)
    # single number
    m2 = re.search(r'\b(\d+)\b', s)
    if m2 and "max" not in s.lower():
        n = int(m2.group(1))
        return (n, n, None)
    # otherwise keep text
    return (None, None, s.strip())

async def import_plan_from_rows(user_id: int, rows: list[dict[str, str]]) -> int:
    """Replace user's plan with rows. Returns number of inserted exercises."""
    # wipe existing plan
    await delete_user_plan_only(user_id)
    inserted = 0
    order_idx = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for r in rows:
            day_raw = str(r.get("day_label", "")).strip().upper()
            day_label = DAY_NORMALIZE.get(day_raw, r.get("day_label", "").strip() or "Unknown")
            name = str(r.get("name", "")).strip()
            if not name:
                continue
            try:
                sets = int(str(r.get("sets", "0")).strip().split()[0])
            except Exception:
                sets = 3
            reps_min, reps_max, reps_text = parse_reps(str(r.get("reps", "")).strip())
            rest_sec = parse_rest_to_seconds(str(r.get("rest", "")).strip())
            await db.execute(
                """INSERT INTO exercises (user_id, name, day_label, sets, reps_min, reps_max, order_idx, rest_sec, reps_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, name, day_label, sets, reps_min if reps_min is not None else 0,
                 reps_max if reps_max is not None else 0, order_idx, rest_sec, reps_text)
            )
            order_idx += 1
            inserted += 1
        await db.commit()
    return inserted

@router.message(Command("plan_import"))
async def cmd_plan_import(message: Message, state: FSMContext):
    await message.answer(
        "Inviami il file **Excel (.xlsx)** o **CSV** con le colonne:\n"
        "`Allenamento | Esercizio | Serie | Ripetizioni | Recupero`.\n"
        "Esempio: LOWER / PULL / PUSH in *Allenamento*.",
        parse_mode="Markdown"
    )
    await state.set_state(ImportState.waiting_file)

@router.message(ImportState.waiting_file, F.document)
async def handle_plan_file(message: Message, state: FSMContext, bot: Bot):
    # Download file
    file = await bot.get_file(message.document.file_id)
    ext = (message.document.file_name or "").lower()
    local_path = os.path.join(os.getcwd(), f"upload_{message.from_user.id}_{message.document.file_unique_id}")
    await bot.download_file(file.file_path, destination=local_path)

    rows: list[dict[str, str]] = []
    try:
        if ext.endswith(".xlsx"):
            import pandas as pd
            df = pd.read_excel(local_path)
        elif ext.endswith(".csv"):
            import pandas as pd
            # try ; first, then ,
            try:
                df = pd.read_csv(local_path, sep=";")
            except Exception:
                df = pd.read_csv(local_path)
        else:
            await message.answer("Formato non supportato. Invia un file .xlsx o .csv.")
            return

        # Normalize headers
        df_cols = {str(c).strip().lower(): c for c in df.columns}
        missing = [k for k in HEADER_MAP.keys() if k not in df_cols]
        if missing:
            await message.answer(f"Mancano colonne: {', '.join(missing)}. Controlla l'intestazione.")
            return

        for _, row in df.iterrows():
            rows.append({
                "day_label": str(row[df_cols["allenamento"]]).strip(),
                "name": str(row[df_cols["esercizio"]]).strip(),
                "sets": str(row[df_cols["serie"]]).strip(),
                "reps": str(row[df_cols["ripetizioni"]]).strip(),
                "rest": str(row[df_cols["recupero"]]).strip(),
            })

        user = await get_or_create_user(message.from_user.id)
        inserted = await import_plan_from_rows(user["id"], rows)
        await message.answer(f"✅ Piano importato: {inserted} esercizi. Ora puoi usare /workout.")
        await state.clear()
    except Exception as e:
        await message.answer(f"Errore durante l'import: {e}")
        await state.clear()
    finally:
        try:
            os.remove(local_path)
        except Exception:
            pass

# ====================
# App entry
# ====================

async def main():
    await init_db()
    await ensure_migrations()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("Bot avviato. Listening...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
