import sys, os, asyncio
# garantisce che 'app' sia importabile anche se lanci da fuori cartella
sys.path.append(os.path.dirname(__file__))

from app.config import bot, dp
from app.handlers import get_routers
from app.db import engine, Base
from app.models import User, WorkoutLog

async def main():
    # Create database tables if they don't exist
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables checked/created")

    for r in get_routers():
        dp.include_router(r)

    print("🤖 Bot avviato (struttura modulare).")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
