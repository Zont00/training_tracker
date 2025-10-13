import io, json
import pandas as pd
from datetime import datetime, timedelta
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.db import get_db
from app.models import User, WorkoutLog, TrainingPlan
from app.utils.plan_parser import parse_plan_from_df

router = Router()

def _get_user(db, tg_user: types.User) -> User:
    user = db.get(User, tg_user.id)
    if not user:
        user = User(id=tg_user.id, username=tg_user.username or "")
        db.add(user)
        db.commit()
    return user

def _create_template_excel() -> io.BytesIO:
    """Create an Excel template with example data for workout plan import"""
    # Create sample data for the template
    data = {
        'Allenamento': ['Giorno 1', 'Giorno 1', 'Giorno 1', 'Giorno 2', 'Giorno 2'],
        'Esercizio': ['Panca piana', 'Squat', 'Stacco', 'Military Press', 'Trazioni'],
        'Serie': [3, 4, 3, 4, 3],
        'Ripetizioni': [8, 10, 8, 8, 'MAX'],
        'Recupero': ['90s', '120s', '180s', '90s', '60s']
    }
    
    df = pd.DataFrame(data)
    
    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Scheda Allenamento', index=False)
        
        # Get the workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets['Scheda Allenamento']
        
        # Add some formatting or instructions if needed
        # For now, just ensure the columns are visible
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    output.seek(0)
    return output

@router.message(Command("import_plan"))
async def import_plan_cmd(message: types.Message):
    # Create the template
    template_file = _create_template_excel()
    
    # Create keyboard with download option
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Scarica Template", callback_data="download_template")
    kb.button(text="📤 Carica Scheda", callback_data="import:prompt")
    kb.adjust(1)
    
    await message.answer(
        "📋 <b>Importa la tua scheda di allenamento</b>\n\n"
        "Puoi scaricare un template Excel precompilato per facilitare la creazione della tua scheda.\n\n"
        "📝 <b>Colonne richieste:</b>\n"
        "• <b>Allenamento</b>: Nome del giorno (es. 'Giorno 1', 'Push', ecc.)\n"
        "• <b>Esercizio</b>: Nome dell'esercizio\n"
        "• <b>Serie</b>: Numero di serie\n"
        "• <b>Ripetizioni</b>: Numero di ripetizioni o 'MAX'\n"
        "• <b>Recupero</b>: Tempo di recupero (es. '60s', '90s', '2m')\n\n"
        "💡 <i>Scarica il template e modificalo con i tuoi esercizi!</i>",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "import:prompt")
async def import_prompt(cb: types.CallbackQuery):
    # Create the template for download
    template_file = _create_template_excel()
    
    # Create keyboard with download option
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Scarica Template", callback_data="download_template")
    kb.adjust(1)
    
    await cb.message.answer(
        "📤 <b>Carica la tua scheda</b>\n\n"
        "Inviami un file <b>.xlsx</b> con le colonne: <b>Allenamento, Esercizio, Serie, Ripetizioni, Recupero</b>.\n\n"
        "💡 <i>Se non hai un file, scarica prima il template!</i>",
        reply_markup=kb.as_markup()
    )
    await cb.answer()

@router.callback_query(F.data == "download_template")
async def download_template_callback(cb: types.CallbackQuery):
    # Create the template
    template_file = _create_template_excel()
    
    # Send the file
    await cb.message.answer_document(
        types.BufferedInputFile(
            template_file.getvalue(),
            filename="template_scheda_allenamento.xlsx"
        ),
        caption="📥 <b>Template Scheda Allenamento</b>\n\n"
                "Scarica questo file, modificalo con i tuoi esercizi e caricamelo con /import_plan.\n\n"
                "📝 <b>Istruzioni:</b>\n"
                "1. Apri il file in Excel\n"
                "2. Modifica gli esercizi con i tuoi\n"
                "3. Salva il file\n"
                "4. Inviamelo con /import_plan\n\n"
                "💡 <i>Mantieni lo stesso formato delle colonne!</i>"
    )
    await cb.answer()


@router.message(F.document)
async def handle_excel(message: types.Message):
    if not message.document.file_name.lower().endswith(".xlsx"):
        return await message.answer("⚠️ Il file deve essere un <b>.xlsx</b> (Excel).")

    db = get_db()
    user = _get_user(db, message.from_user)
    try:
        file = await message.bot.get_file(message.document.file_id)
        buf = io.BytesIO()
        await message.bot.download_file(file.file_path, destination=buf)
        buf.seek(0)

        df = pd.read_excel(buf)
        plan = parse_plan_from_df(df)

        # Generate plan name from filename or use default
        plan_name = message.document.file_name.replace('.xlsx', '').replace('_', ' ').title()
        if not plan_name or plan_name.isspace():
            plan_name = f"Scheda {datetime.now().strftime('%d/%m/%Y')}"

        # Create new training plan record
        new_plan = TrainingPlan(
            user_id=user.id,
            plan_name=plan_name,
            plan_data=json.dumps(plan, ensure_ascii=False),
            created_at=datetime.now(),
            is_active=1
        )
        db.add(new_plan)

        # Also update user's current training plan for backward compatibility
        user.training_plan = json.dumps(plan, ensure_ascii=False)
        user.current_day = None
        user.exercise_idx = 0
        user.set_idx = 0
        db.commit()

        # Crea tastiera con pulsanti azione rapida
        kb = InlineKeyboardBuilder()
        kb.button(text="🏋️ Inizia Allenamento", callback_data="workout:start")
        kb.button(text="📋 Vedi Piano", callback_data="view_plan")
        kb.button(text="📈 Vedi Progressi", callback_data="view_progress")
        kb.adjust(2, 1)

        total_exercises = sum(len(exercises) for exercises in plan.values())
        
        await message.answer(
            "🎉 <b>Scheda importata con successo!</b>\n\n"
            f"📊 <b>Dettagli importazione:</b>\n"
            f"• Nome scheda: <b>{plan_name}</b>\n"
            f"• Allenamenti trovati: <b>{len(plan)}</b>\n"
            f"• Esercizi totali: <b>{total_exercises}</b>\n"
            f"• Giorni: <b>{', '.join(plan.keys())}</b>\n\n"
            f"💡 <i>Ora puoi iniziare subito il tuo allenamento!</i>",
            reply_markup=kb.as_markup()
        )
    except Exception as e:
        await message.answer(f"❌ Errore nell'importazione: <code>{e}</code>")
    finally:
        db.close()
