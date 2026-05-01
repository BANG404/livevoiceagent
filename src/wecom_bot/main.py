"""CLI entrypoint for the Enterprise WeChat guard-query bot."""

from __future__ import annotations

import asyncio
import logging

from agent.config import settings
from wecom_bot.bridge import WeComGuardQueryBot


def _log_level(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


async def _main() -> None:
    if not settings.wecom_bot_id or not settings.wecom_bot_secret:
        raise RuntimeError(
            "Set WECOM_BOT_ID and WECOM_BOT_SECRET before starting the WeCom bot bridge."
        )

    logging.basicConfig(
        level=_log_level(settings.wecom_log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bot = WeComGuardQueryBot(settings)
    try:
        await bot.run_forever()
    finally:
        await bot.aclose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
