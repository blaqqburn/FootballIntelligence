import asyncio
import unittest
from types import SimpleNamespace

from bot_config import (
    BotConfigurationError,
    load_bot_configuration,
    verify_development_bot,
)


class BotConfigurationTests(unittest.TestCase):
    def test_development_requires_test_token(self):
        with self.assertRaisesRegex(
            BotConfigurationError, "FI_TEST_BOT_TOKEN"
        ):
            load_bot_configuration({
                "FI_ENV": "development",
                "FI_TEST_BOT_USERNAME": "football_test_bot",
                "BOT_TOKEN": "must-not-be-read",
            })

    def test_development_requires_expected_username_without_exposing_token(self):
        test_token = "test-token-sentinel"
        with self.assertRaises(BotConfigurationError) as error:
            load_bot_configuration({
                "FI_ENV": "development",
                "FI_TEST_BOT_TOKEN": test_token,
                "BOT_TOKEN": "production-token-sentinel",
            })

        self.assertNotIn(test_token, str(error.exception))
        self.assertNotIn("production-token-sentinel", str(error.exception))

    def test_development_uses_only_test_credentials_and_normalizes_username(self):
        configuration = load_bot_configuration({
            "FI_ENV": "development",
            "FI_TEST_BOT_TOKEN": "test-token-sentinel",
            "FI_TEST_BOT_USERNAME": "@Football_Test_Bot",
            "BOT_TOKEN": "production-token-sentinel",
        })

        self.assertEqual(configuration.environment, "development")
        self.assertEqual(configuration.token, "test-token-sentinel")
        self.assertEqual(configuration.expected_username, "Football_Test_Bot")

    def test_development_username_must_be_valid(self):
        with self.assertRaisesRegex(
            BotConfigurationError, "valid Telegram username"
        ):
            load_bot_configuration({
                "FI_ENV": "development",
                "FI_TEST_BOT_TOKEN": "test-token-sentinel",
                "FI_TEST_BOT_USERNAME": "invalid username",
            })

    def test_environment_must_be_explicit(self):
        with self.assertRaisesRegex(BotConfigurationError, "FI_ENV"):
            load_bot_configuration({"BOT_TOKEN": "must-not-be-read"})

    def test_test_bot_identity_is_checked_and_bot_is_closed(self):
        created = {}

        class FakeBot:
            def __init__(self, token):
                created["token"] = token

            async def initialize(self):
                created["initialized"] = True

            async def get_me(self):
                return SimpleNamespace(username="football_test_bot")

            async def shutdown(self):
                created["closed"] = True

        asyncio.run(verify_development_bot(
            "test-token-sentinel",
            "Football_Test_Bot",
            FakeBot,
        ))

        self.assertEqual(created["token"], "test-token-sentinel")
        self.assertTrue(created["initialized"])
        self.assertTrue(created["closed"])

    def test_test_bot_username_mismatch_fails_without_credentials(self):
        test_token = "test-token-sentinel"

        class FakeBot:
            def __init__(self, token):
                pass

            async def initialize(self):
                pass

            async def get_me(self):
                return SimpleNamespace(username="other_test_bot")

            async def shutdown(self):
                pass

        with self.assertRaises(BotConfigurationError) as error:
            asyncio.run(verify_development_bot(
                test_token, "football_test_bot", FakeBot
            ))

        self.assertNotIn(test_token, str(error.exception))
        self.assertNotIn("other_test_bot", str(error.exception))

    def test_test_bot_api_error_is_redacted(self):
        test_token = "test-token-sentinel"

        class FakeBot:
            def __init__(self, token):
                self.token = token

            async def initialize(self):
                raise ValueError(f"request failed for {self.token}")

            async def get_me(self):
                raise AssertionError("get_me should not run")

            async def shutdown(self):
                raise AssertionError("uninitialized bot should not close")

        with self.assertRaises(RuntimeError) as error:
            asyncio.run(verify_development_bot(
                test_token, "football_test_bot", FakeBot
            ))

        self.assertEqual(
            str(error.exception),
            "Could not verify the configured test bot identity.",
        )
        self.assertNotIn(test_token, str(error.exception))

    def test_test_bot_constructor_error_is_redacted(self):
        test_token = "test-token-sentinel"

        def broken_bot_factory(token):
            raise ValueError(f"invalid token: {token}")

        with self.assertRaises(RuntimeError) as error:
            asyncio.run(verify_development_bot(
                test_token, "football_test_bot", broken_bot_factory
            ))

        self.assertEqual(
            str(error.exception),
            "Could not verify the configured test bot identity.",
        )
        self.assertNotIn(test_token, str(error.exception))


if __name__ == "__main__":
    unittest.main()
