import sys, os, asyncio
# garantisce che 'app' sia importabile anche se lanci da fuori cartella
sys.path.append(os.path.dirname(__file__))

from app.config import bot, dp, DATABASE_URL
from app.handlers import get_routers
from app.db import engine, Base
from app.models import User, WorkoutLog, TrainingPlan

async def main():
    # Debug info per deployment
    print(f"🚀 Avvio bot su Railway...")
    print(f"📊 DATABASE_URL: {DATABASE_URL[:50]}...")  # Mostra solo i primi 50 caratteri per sicurezza
    
    # Create database tables if they don't exist
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables checked/created")
    except Exception as e:
        print(f"❌ Errore creazione tabelle: {e}")
        return

    for r in get_routers():
        dp.include_router(r)

    print("🤖 Bot avviato (struttura modulare).")
    print("⏳ Inizio polling...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Errore durante il polling: {e}")

if __name__ == "__main__":
    asyncio.run(main())
