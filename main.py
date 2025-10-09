import sys, os, asyncio
# garantisce che 'app' sia importabile anche se lanci da fuori cartella
sys.path.append(os.path.dirname(__file__))

from app.config import bot, dp
from app.handlers import get_routers

async def main():
    for r in get_routers():
        dp.include_router(r)

    print("🤖 Bot avviato (struttura modulare).")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
