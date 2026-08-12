from aiogram import Bot, Dispatcher

from app.bot.handlers import router
from app.core.config import settings


def create_bot() -> Bot:
    token = settings.TELEGRAM_BOT_TOKEN

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    return Bot(token=token)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_telegram_polling() -> None:

    bot = create_bot()
    dispatcher = create_dispatcher()

    await dispatcher.start_polling(
        bot,
        handle_signals=False,
        allowed_updates=dispatcher.resolve_used_update_types(),
    )
