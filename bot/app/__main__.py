import logging

from aiohttp import web

from app.config import get_settings
from app.main import PORT, create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Webhook is registered by the one-shot `bot-setup`, never by the replicas.
    web.run_app(create_app(get_settings()), host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
