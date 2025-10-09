import json
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.db import get_db
from app.models import User, WorkoutLog
from app.keyboards import reset_confirmation_menu

router = Router()
awaiting_set: dict[int, bool] = {}

def _get_user(db, tg_user: types.User) -> User:
    user = db.query(User).filter(User.id == tg_user.id).first()
    if not user:
        user = User(id=tg_user.id, username=tg_user.username or "")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@router.message(Command("workout"))
async def workout_cmd(message: types.Message):
    await _start_workout_flow(message, message.from_user)

@router.callback_query(F.data == "workout:start")
async def workout_start_callback(cb: types.CallbackQuery):
    await _start_workout_flow(cb.message, cb.from_user)
    await cb.answer()

@router.message(Command("view_plan"))
async def view_plan_cmd(message: types.Message):
    await _display_plan(message, message.from_user)

@router.callback_query(F.data == "view_plan")
async def view_plan_callback(cb: types.CallbackQuery):
    await _display_plan(cb.message, cb.from_user)
    await cb.answer()

@router.message(Command("progress"))
async def progress_cmd(message: types.Message):
    await _display_progress(message, message.from_user)

@router.callback_query(F.data == "view_progress")
async def progress_callback(cb: types.CallbackQuery):
    await _display_progress(cb.message, cb.from_user)
    await cb.answer()

@router.callback_query(F.data == "reset:confirm")
async def reset_confirm_callback(cb: types.CallbackQuery):
    await cb.message.answer(
        "⚠️ **Conferma Reset**\n\n"
        "Sei sicuro di voler eliminare la scheda e tutti i progressi?\n"
        "Questa operazione non può essere annullata.",
        reply_markup=reset_confirmation_menu()
    )
    await cb.answer()

@router.callback_query(F.data == "reset:cancel")
async def reset_cancel_callback(cb: types.CallbackQuery):
    await cb.message.answer("✅ Reset annullato.")
    await cb.answer()

@router.callback_query(F.data == "reset:execute")
async def reset_execute_callback(cb: types.CallbackQuery):
    db = get_db()
    user = _get_user(db, cb.from_user)
    
    # Elimina tutti i log dell'utente
    db.query(WorkoutLog).filter(WorkoutLog.user_id == user.id).delete()
    
    # Resetta i dati dell'utente
    user.training_plan = None
    user.current_day = None
    user.exercise_idx = 0
    user.set_idx = 0
    db.commit()
    db.close()
    
    await cb.message.answer("🔄 **Reset completato!**\n\nScheda e progressi eliminati con successo.")
    await cb.answer()

@router.callback_query(F.data == "back:set")
async def back_set_callback(cb: types.CallbackQuery):
    db = get_db()
    user = _get_user(db, cb.from_user)
    
    if not user.training_plan or not user.current_day:
        db.close()
        await cb.answer("⚠️ Nessun workout attivo.")
        return

    plan = json.loads(user.training_plan)
    exercises = plan.get(user.current_day, [])
    if user.exercise_idx >= len(exercises):
        db.close()
        await cb.answer("🏁 Allenamento concluso.")
        return

    # Se siamo alla prima serie di un esercizio e non siamo al primo esercizio, torna all'esercizio precedente
    if user.set_idx == 0 and user.exercise_idx > 0:
        user.exercise_idx -= 1
        ex_prev = exercises[user.exercise_idx]
        total_sets_prev = int(ex_prev["sets"])
        user.set_idx = total_sets_prev - 1  # ultima serie dell'esercizio precedente
        db.commit()
        db.close()
        await cb.message.answer(f"↩️ **Tornato all'esercizio precedente**: {ex_prev['name']} — serie {user.set_idx + 1}/{total_sets_prev}")
        await _prompt_next_set(cb.message, user, db)
        await cb.answer()
        return

    ex = exercises[user.exercise_idx]
    total_sets = int(ex["sets"])
    
    # Trova l'ultimo log per questo esercizio nel giorno corrente
    last_log = db.query(WorkoutLog).filter(
        WorkoutLog.user_id == user.id,
        WorkoutLog.day == user.current_day,
        WorkoutLog.exercise == ex['name']
    ).order_by(WorkoutLog.ts.desc()).first()

    if last_log and last_log.set_number == user.set_idx:
        # Se c'è un log per l'ultima serie registrata, eliminarlo
        db.delete(last_log)
        user.set_idx = max(0, user.set_idx - 1)
        db.commit()
        await cb.message.answer(f"↩️ **Set annullato**: {ex['name']} — set {last_log.set_number}")
    else:
        # Se non c'è un log (serie saltata), semplicemente decrementa l'indice
        user.set_idx = max(0, user.set_idx - 1)
        db.commit()
        await cb.message.answer(f"↩️ **Tornato indietro**: {ex['name']} — serie {user.set_idx + 1}/{total_sets}")

    db.close()
    await _prompt_next_set(cb.message, user, db)
    await cb.answer()

@router.callback_query(F.data == "skip:set")
async def skip_set_callback(cb: types.CallbackQuery):
    db = get_db()
    user = _get_user(db, cb.from_user)
    
    if not user.training_plan or not user.current_day:
        db.close()
        await cb.answer("⚠️ Nessun workout attivo.")
        return

    plan = json.loads(user.training_plan)
    exercises = plan.get(user.current_day, [])
    if user.exercise_idx >= len(exercises):
        db.close()
        await cb.answer("🏁 Allenamento concluso.")
        return

    ex = exercises[user.exercise_idx]
    total_sets = int(ex["sets"])

    # Passa alla serie successiva senza registrare nulla
    user.set_idx += 1
    db.commit()

    # Se abbiamo superato l'ultima serie, passiamo all'esercizio successivo
    if user.set_idx >= total_sets:
        user.exercise_idx += 1
        user.set_idx = 0
        db.commit()
        db.close()
        await cb.answer()
        await _prompt_next_set(cb.message, user, db)
    else:
        db.close()
        await cb.message.answer(f"⏭️ **Set saltato**: {ex['name']} — serie {user.set_idx}/{total_sets}")
        await _prompt_next_set(cb.message, user, db)
        await cb.answer()

@router.callback_query(F.data == "view_plan_current")
async def view_plan_current_callback(cb: types.CallbackQuery):
    db = get_db()
    user = _get_user(db, cb.from_user)
    
    if not user.training_plan or not user.current_day:
        db.close()
        await cb.answer("⚠️ Nessun workout attivo.")
        return

    plan = json.loads(user.training_plan)
    current_day = user.current_day
    
    if current_day not in plan:
        db.close()
        await cb.answer("⚠️ Giorno di allenamento non trovato.")
        return

    exercises = plan[current_day]
    response = f"📋 **Piano di Allenamento - {current_day}**\n\n"
    
    for i, ex in enumerate(exercises, 1):
        current_indicator = "🟢 " if i-1 == user.exercise_idx else "   "
        response += f"{current_indicator}{i}. {ex['name']} - {ex['sets']}x{ex['reps']} - Recupero: {ex['rest']}\n"
    
    response += f"\n📍 <i>Attualmente all'esercizio {user.exercise_idx + 1}</i>"
    
    await cb.message.answer(response)
    db.close()
    await cb.answer()

@router.callback_query(F.data == "cancel_workout")
async def cancel_workout_callback(cb: types.CallbackQuery):
    db = get_db()
    user = _get_user(db, cb.from_user)
    
    if not user.training_plan or not user.current_day:
        db.close()
        await cb.answer("⚠️ Nessun workout attivo.")
        return

    # Crea tastiera di conferma
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Conferma Annullamento", callback_data="cancel_workout_confirm")
    kb.button(text="❌ Continua Allenamento", callback_data="cancel_workout_cancel")
    kb.adjust(1)
    
    await cb.message.answer(
        "⚠️ **Conferma Annullamento**\n\n"
        "Sei sicuro di voler annullare l'allenamento in corso?\n"
        "Tutti i progressi non salvati andranno persi.",
        reply_markup=kb.as_markup()
    )
    db.close()
    await cb.answer()

@router.callback_query(F.data == "cancel_workout_confirm")
async def cancel_workout_confirm_callback(cb: types.CallbackQuery):
    db = get_db()
    user = _get_user(db, cb.from_user)
    
    current_day = user.current_day
    user.current_day = None
    user.exercise_idx = 0
    user.set_idx = 0
    awaiting_set[user.id] = False
    db.commit()
    db.close()
    
    await cb.message.answer(f"❌ Allenamento <b>{current_day}</b> annullato.")
    await cb.answer()

@router.callback_query(F.data == "cancel_workout_cancel")
async def cancel_workout_cancel_callback(cb: types.CallbackQuery):
    await cb.message.answer("✅ Allenamento ripreso.")
    await cb.answer()

@router.callback_query(F.data == "workout_cancel")
async def workout_cancel_callback(cb: types.CallbackQuery):
    await cb.message.answer("❌ Allenamento annullato.")
    await cb.answer()


async def _display_plan(message: types.Message, tg_user: types.User):
    db = get_db()
    user = _get_user(db, tg_user)

    if not user.training_plan:
        db.close()
        return await message.answer("⚠️ Nessuna scheda caricata. Usa /import_plan.")

    plan = json.loads(user.training_plan)
    if not plan:
        db.close()
        return await message.answer("⚠️ La scheda è vuota. Reimporta il file.")

    response = "📊 **Il tuo piano di allenamento:**\n\n"
    
    for day, exercises in plan.items():
        response += f"🏷️ **{day}**\n"
        for i, ex in enumerate(exercises, 1):
            response += f"  {i}. {ex['name']} - {ex['sets']}x{ex['reps']} - Recupero: {ex['rest']}\n"
        response += "\n"
    
    await message.answer(response)
    db.close()

async def _display_progress(message: types.Message, tg_user: types.User):
    db = get_db()
    user = _get_user(db, tg_user)

    if not user.training_plan:
        db.close()
        return await message.answer("📈 **I tuoi progressi**\n\nNessuna scheda caricata. Usa /import_plan.")

    plan = json.loads(user.training_plan)
    
    # Recupera tutti i log dell'utente
    logs = db.query(WorkoutLog).filter(
        WorkoutLog.user_id == user.id
    ).order_by(WorkoutLog.ts.asc()).all()
    
    if not logs:
        db.close()
        return await message.answer("📈 **I tuoi progressi**\n\nNessun dato di allenamento registrato.")

    # Raggruppa i log per giorno di allenamento e poi per esercizio
    workout_progress = {}
    for log in logs:
        if log.day not in workout_progress:
            workout_progress[log.day] = {}
        if log.exercise not in workout_progress[log.day]:
            workout_progress[log.day][log.exercise] = {}
        
        date_str = log.ts.strftime("%d/%m")
        if date_str not in workout_progress[log.day][log.exercise]:
            workout_progress[log.day][log.exercise][date_str] = []
        workout_progress[log.day][log.exercise][date_str].append(log)

    response = "📈 **I tuoi progressi**\n\n"
    
    # Per ogni giorno nel piano (nell'ordine della scheda)
    for day_name in plan.keys():
        if day_name in workout_progress and workout_progress[day_name]:
            response += f"🏷️ **{day_name}**\n"
            
            # Per ogni esercizio nel giorno (nell'ordine della scheda)
            for exercise in plan[day_name]:
                exercise_name = exercise['name']
                if exercise_name in workout_progress[day_name]:
                    response += f"  🏋️ {exercise_name}:\n"
                    
                    # Per ogni data in cui è stato fatto l'esercizio (ordinate cronologicamente)
                    for date_str in sorted(workout_progress[day_name][exercise_name].keys()):
                        logs_list = workout_progress[day_name][exercise_name][date_str]
                        response += f"    📅 {date_str}: "
                        # Mostra tutti i set del giorno in formato compatto
                        sets = [f"{log.weight}kg × {log.reps}" for log in logs_list]
                        response += " ".join(sets) + "\n"
                    
                    response += "\n"
            
            response += "\n"
    
    await message.answer(response)
    db.close()

async def _start_workout_flow(message: types.Message, tg_user: types.User):
    db = get_db()
    user = _get_user(db, tg_user)

    if not user.training_plan:
        db.close()
        return await message.answer("⚠️ <b>Nessuna scheda caricata</b>\n\nUsa il comando /import_plan per caricare la tua scheda di allenamento.")

    plan = json.loads(user.training_plan)
    if not plan:
        db.close()
        return await message.answer("⚠️ <b>La scheda è vuota</b>\n\nReimporta il file con /import_plan.")

    kb = InlineKeyboardBuilder()
    for day in plan.keys():
        kb.button(text=f"🏷️ {day}", callback_data=f"day:{day}")
    kb.button(text="❌ Annulla", callback_data="workout_cancel")
    kb.adjust(1)
    
    response = (
        "🏋️‍♂️ <b>Inizia il tuo allenamento!</b>\n\n"
        "Scegli il giorno di allenamento che vuoi fare oggi:\n\n"
        "💡 <i>Puoi visualizzare il piano completo con /view_plan</i>"
    )
    
    await message.answer(response, reply_markup=kb.as_markup())
    db.close()

@router.callback_query(F.data.startswith("day:"))
async def choose_day(cb: types.CallbackQuery):
    day = cb.data.split(":", 1)[1]
    db = get_db()
    user = _get_user(db, cb.from_user)

    user.current_day = day
    user.exercise_idx = 0
    user.set_idx = 0
    db.commit()

    await cb.answer()
    await cb.message.answer(f"🏷️ Allenamento scelto: <b>{day}</b> ✅")
    await _prompt_next_set(cb.message, user, db)
    db.close()

async def _prompt_next_set(message: types.Message, user: User, db):
    plan = json.loads(user.training_plan)
    exercises = plan.get(user.current_day, [])
    if user.exercise_idx >= len(exercises):
        day = user.current_day
        user.current_day = None
        user.exercise_idx = 0
        user.set_idx = 0
        db.commit()
        return await message.answer(f"🎉 Allenamento <b>{day}</b> completato! 💪🔥")

    ex = exercises[user.exercise_idx]
    total_sets = int(ex["sets"])

    if user.set_idx >= total_sets:
        user.exercise_idx += 1
        user.set_idx = 0
        db.commit()
        return await _prompt_next_set(message, user, db)


    # Se è l'inizio di un nuovo esercizio (prima serie), mostra il recap dei progressi
    progress_recap = ""
    if user.set_idx == 0:
        # Recupera tutti i log per questo esercizio
        exercise_logs = db.query(WorkoutLog).filter(
            WorkoutLog.user_id == user.id,
            WorkoutLog.exercise == ex['name']
        ).order_by(WorkoutLog.ts.desc()).all()
        
        if exercise_logs:
            # Raggruppa i log per giorno (data)
            day_progress = {}
            for log in exercise_logs:
                date_str = log.ts.strftime("%d/%m")
                if date_str not in day_progress:
                    day_progress[date_str] = []
                day_progress[date_str].append(log)
            
            # Prendi gli ultimi 5 giorni (dal più recente)
            recent_days = sorted(day_progress.keys(), reverse=True)[:5]
            
            if recent_days:
                progress_recap = "\n\n📈 **Progressi recenti:**\n"
                for date_str in recent_days:
                    logs_list = day_progress[date_str]
                    progress_recap += f"  {date_str}: "
                    # Mostra tutti i set del giorno in formato compatto
                    sets = [f"{log.weight}kg × {log.reps}" for log in logs_list]
                    progress_recap += " ".join(sets) + "\n"

    awaiting_set[user.id] = True
    
    # Crea la tastiera con pulsanti Indietro, Salta, Piano e Annulla
    kb = InlineKeyboardBuilder()
    
    # Mostra "Indietro" se ci sono set precedenti o se non siamo al primo esercizio
    if user.set_idx > 0 or (user.set_idx == 0 and user.exercise_idx > 0):
        kb.button(text="↩️ Indietro", callback_data="back:set")
    
    kb.button(text="⏭️ Salta Serie", callback_data="skip:set")
    kb.button(text="📋 Vedi Piano", callback_data="view_plan_current")
    kb.button(text="❌ Annulla Allenamento", callback_data="cancel_workout")
    kb.adjust(2)
    
    # Messaggio più descrittivo e user-friendly
    message_text = (
        f"💪 <b>{ex['name']}</b>\n\n"
        f"📊 <b>Progresso:</b> Serie {user.set_idx + 1} di {total_sets}\n"
        f"🎯 <b>Obiettivo:</b> {ex['reps']} ripetizioni\n"
        f"⏱️ <b>Recupero:</b> {ex['rest']}\n"
    )
    
    if progress_recap:
        message_text += progress_recap
    
    message_text += (
        f"\n📝 <b>Inserisci i dati della serie:</b>\n"
        f"• Formato: <code>peso reps</code>\n"
        f"• Esempio: <code>50 10</code>\n\n"
        f"💡 <i>Puoi usare la virgola per i decimali (es. 52,5)</i>"
    )
    
    await message.answer(message_text, reply_markup=kb.as_markup())

@router.message()
async def capture_set(message: types.Message):
    if not awaiting_set.get(message.from_user.id):
        return

    try:
        p, r = message.text.strip().split()
        weight = p.replace(",", ".")
        reps = int(r)
    except Exception:
        return await message.answer("⚠️ Formato invalido. Usa <code>peso reps</code> (es. <code>50 10</code>).")

    db = get_db()
    user = _get_user(db, message.from_user)
    if not user.training_plan or not user.current_day:
        awaiting_set[message.from_user.id] = False
        db.close()
        return await message.answer("⚠️ Nessun workout attivo. Usa /workout.")

    plan = json.loads(user.training_plan)
    exercises = plan.get(user.current_day, [])
    if user.exercise_idx >= len(exercises):
        awaiting_set[message.from_user.id] = False
        db.close()
        return await message.answer("🏁 Allenamento concluso.")

    ex = exercises[user.exercise_idx]
    set_number = user.set_idx + 1
    total_sets = int(ex["sets"])

    log = WorkoutLog(
        user_id=user.id,
        day=user.current_day,
        exercise=ex["name"],
        set_number=set_number,
        weight=weight,
        reps=reps,
    )
    db.add(log)

    user.set_idx += 1
    db.commit()
    awaiting_set[message.from_user.id] = False

    await message.answer(f"✅ Registrato: <b>{ex['name']}</b> — set {set_number}/{total_sets}: <b>{weight}kg × {reps}</b>")
    await _prompt_next_set(message, user, db)
    db.close()
