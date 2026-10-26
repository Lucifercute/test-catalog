import httpx
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.backend import BackendClient
from app.config import Settings
from app.handlers import build_router

WEBHOOK_PATH = "/tg/webhook"
PORT = 8080


def build_dispatcher() -> Dispatcher:
    # FSM is off: no MemoryStorage, nothing per-user kept in the process.
    dispatcher = Dispatcher(disable_fsm=True)
    dispatcher.include_router(build_router())
    return dispatcher


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_app(
    settings: Settings,
    *,
    bot: Bot | None = None,
    backend_transport: httpx.AsyncBaseTransport | None = None,
) -> web.Application:
    bot = bot or Bot(settings.bot_token.get_secret_value())
    dispatcher = build_dispatcher()
    dispatcher["settings"] = settings

    async def on_startup(dispatcher: Dispatcher) -> None:
        # One pooled client per process, kept in dispatcher data (not a module global).
        http = httpx.AsyncClient(
            base_url=str(settings.backend_url),
            timeout=settings.backend_timeout,
            transport=backend_transport,
        )
        dispatcher["http"] = http
        dispatcher["backend"] = BackendClient(http, settings.internal_token.get_secret_value())

    async def on_shutdown(dispatcher: Dispatcher) -> None:
        # The bot session is closed by SimpleRequestHandler's own shutdown hook.
        await dispatcher["http"].aclose()

    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/health", health)
    # handle_in_background=False: the response waits for the handler, so an exception
    # (e.g. backend down) becomes HTTP 500 and Telegram redelivers the update, possibly to
    # another replica. With True the update would be acked first and lost on failure.
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        handle_in_background=False,
        secret_token=settings.webhook_secret.get_secret_value(),
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)
    return app
