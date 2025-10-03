# Gym Bot MVP (Telegram, aiogram v3)

MVP minimale con **solo onboarding** (scelta unità e creazione piano base) e **workout guidato** (inserimento set con `peso reps`).

## 🚀 Avvio rapido

1) Crea un Bot su Telegram con **@BotFather** e copia il token.

2) Preparazione ambiente
```bash
python -m venv .venv
source .venv/bin/activate   # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3) Configura variabili d'ambiente
```bash
export BOT_TOKEN="IL_TUO_TOKEN"
# (opzionale) percorso db
export DB_PATH="gymbot.db"
```

4) Avvia il bot
```bash
python main.py
```

## 📲 Uso

- `/start` → onboarding: scegli `kg` o `lbs`. Il bot crea un piano base **Push / Pull / Legs** con alcuni esercizi e range di reps.
- `/workout` → scegli il giorno e inizia. Per ogni serie invia: `peso reps` (es. `62.5 8`) oppure `skip` per saltare.

Alla fine degli esercizi, il bot chiude la sessione. In MVP non c'è ancora /history, /stats, etc.

## 🗄️ Schema DB (SQLite)

- **users**: `id, telegram_id, unit, created_at`
- **exercises**: `id, user_id, name, day_label, sets, reps_min, reps_max, order_idx`
- **workouts**: `id, user_id, date, day_label, notes`
- **sets**: `id, workout_id, exercise_id, set_idx, weight, reps, ts`

## 🧩 Note tecniche

- Libreria: aiogram v3 (polling). Per produzione, usa **webhook**.
- DB: aiosqlite (async). Non blocca l'event loop.
- Stato allenamento: aiogram FSM (`WorkoutState`).

## ➕ Estensioni future (non incluse in MVP)

- Tastiere numeriche/inline per peso/reps.
- Mostrare ultimo record e suggerimento incremento.
- /history, /stats, export CSV/Google Sheet.
- RPE, top set + backoff, deload, reminder programmati.
- Multilingua e alias esercizi.