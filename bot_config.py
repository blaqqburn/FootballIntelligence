"""Environment selection for production and isolated development bot runs."""

import os
import re
from dataclasses import dataclass


class BotConfigurationError(RuntimeError):
    """Raised when the selected bot environment is not safely configured."""


@dataclass(frozen=True)
class BotConfiguration:
    environment: str
    token: str
    expected_username: str = ""


def load_bot_configuration(environ=None):
    values = os.environ if environ is None else environ
    environment = values.get("FI_ENV", "").strip().lower()
    if environment not in {"development", "production"}:
        raise BotConfigurationError(
            "FI_ENV must be explicitly set to 'development' or 'production'."
        )

    if environment == "development":
        token = values.get("FI_TEST_BOT_TOKEN", "").strip()
        username = values.get("FI_TEST_BOT_USERNAME", "").strip().lstrip("@")
        if not token:
            raise BotConfigurationError(
                "FI_TEST_BOT_TOKEN is required in development."
            )
        if not username:
            raise BotConfigurationError(
                "FI_TEST_BOT_USERNAME is required in development."
            )
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            raise BotConfigurationError(
                "FI_TEST_BOT_USERNAME must be a valid Telegram username."
            )
        return BotConfiguration(
            environment="development",
            token=token,
            expected_username=username,
        )

    token = values.get("BOT_TOKEN", "").strip()
    if not token:
        raise BotConfigurationError("BOT_TOKEN is required in production.")
    return BotConfiguration(environment="production", token=token)


def validate_bot_username(expected_username, actual_username):
    if (
        not expected_username
        or not actual_username
        or expected_username.casefold() != actual_username.casefold()
    ):
        raise BotConfigurationError(
            "Telegram bot username does not match FI_TEST_BOT_USERNAME."
        )


async def verify_development_bot(token, expected_username, bot_factory):
    """Verify the test bot identity before the application starts services."""
    bot = None
    initialized = False
    try:
        bot = bot_factory(token=token)
        await bot.initialize()
        initialized = True
        identity = await bot.get_me()
        validate_bot_username(expected_username, identity.username)
    except BotConfigurationError:
        raise
    except Exception:
        raise RuntimeError(
            "Could not verify the configured test bot identity."
        ) from None
    finally:
        if bot is not None and initialized:
            try:
                await bot.shutdown()
            except Exception:
                raise RuntimeError(
                    "Could not safely close the test bot identity check."
                ) from None
