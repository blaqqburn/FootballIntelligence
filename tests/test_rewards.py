import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager

import rewards


class RewardsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = os.path.join(self.directory.name, "test.sqlite3")

    @contextmanager
    def database(self):
        db = sqlite3.connect(self.db_path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _correct_answer(self, challenge):
        return rewards.submit_answer(
            42,
            challenge["token"],
            challenge["question"]["correct"],
            self.db_path,
            now=1_800_000_000,
        )

    def test_correct_answer_awards_fi_stars_once_and_records_badge(self):
        challenge = rewards.issue_question(
            42, self.db_path, now=1_800_000_000
        )

        result = self._correct_answer(challenge)
        replay = self._correct_answer(challenge)
        data = rewards.wallet(42, self.db_path)

        self.assertEqual(result["status"], "correct")
        self.assertEqual(result["awarded"], 10)
        self.assertEqual(result["new_badges"], ["First Goal"])
        self.assertEqual(replay["status"], "replay")
        self.assertEqual(data["fi_stars"], 10)
        self.assertEqual(data["history"][0][0:2], (10, "quiz_correct"))
        self.assertIn("First Goal", data["badges"])

    def test_second_challenge_for_same_question_cannot_award_again_today(self):
        now = 1_800_000_000
        challenge = rewards.issue_question(42, self.db_path, now=now)
        first = rewards.submit_answer(
            42, challenge["token"], challenge["question"]["correct"],
            self.db_path, now=now,
        )
        with self.database() as db:
            db.execute(
                """
                INSERT INTO quiz_challenges
                    (token, user_id, question_id, issued_at, expires_at)
                VALUES ('second-token', 42, ?, ?, ?)
                """,
                (challenge["question"]["id"], now + 1, now + 601),
            )

        duplicate = rewards.submit_answer(
            42, "second-token", challenge["question"]["correct"],
            self.db_path, now=now + 1,
        )

        self.assertEqual(first["status"], "correct")
        self.assertEqual(duplicate["status"], "replay")
        self.assertEqual(rewards.wallet(42, self.db_path)["fi_stars"], 10)

    def test_wallet_badges_and_weekly_leaderboard_use_fi_stars(self):
        now = int(rewards.time.time())
        rewards.register_user(42, "Test fan", self.db_path)

        for offset in range(len(rewards.QUESTIONS)):
            challenge = rewards.issue_question(
                42, self.db_path, now=now + offset
            )
            result = rewards.submit_answer(
                42, challenge["token"], challenge["question"]["correct"],
                self.db_path, now=now + offset,
            )
            self.assertEqual(result["status"], "correct")

        data = rewards.wallet(42, self.db_path)
        leaderboard = rewards.weekly_leaderboard(self.db_path)

        self.assertEqual(data["fi_stars"], 100)
        self.assertEqual(data["weekly_fi_stars"], 100)
        self.assertIn("Playmaker", data["badges"])
        self.assertIn(("Test fan", 100), leaderboard)

    def test_wrong_answer_consumes_question_and_cannot_be_replayed(self):
        challenge = rewards.issue_question(
            42, self.db_path, now=1_800_000_000
        )
        wrong_choice = (challenge["question"]["correct"] + 1) % len(
            challenge["question"]["answers"]
        )

        first = rewards.submit_answer(
            42, challenge["token"], wrong_choice, self.db_path,
            now=1_800_000_000,
        )
        next_question = rewards.issue_question(
            42, self.db_path, now=1_800_000_001
        )

        self.assertEqual(first["status"], "incorrect")
        self.assertNotEqual(
            challenge["question"]["id"], next_question["question"]["id"]
        )

    def test_challenge_is_bound_to_the_issuing_user(self):
        challenge = rewards.issue_question(
            42, self.db_path, now=1_800_000_000
        )

        result = rewards.submit_answer(
            99, challenge["token"], challenge["question"]["correct"],
            self.db_path, now=1_800_000_001,
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(rewards.wallet(99, self.db_path)["fi_stars"], 0)

    def test_daily_cap_limits_rewards_to_100_fi_stars(self):
        rewards.register_user(42, db_path=self.db_path)
        with self.database() as db:
            db.execute(
                "UPDATE users SET fi_stars=90 WHERE user_id=42"
            )
            db.execute(
                """
                INSERT INTO fi_star_transactions
                    (user_id, amount, kind, created_at)
                VALUES (42, 90, 'quiz_correct', ?)
                """,
                (1_800_000_000,),
            )

        first = rewards.issue_question(
            42, self.db_path, now=1_800_000_001
        )
        first_result = self._correct_answer_at(first, 1_800_000_001)
        second = rewards.issue_question(
            42, self.db_path, now=1_800_000_002
        )
        second_result = self._correct_answer_at(second, 1_800_000_002)

        self.assertEqual(first_result["awarded"], 10)
        self.assertEqual(second_result["status"], "daily_limit")
        self.assertEqual(rewards.wallet(42, self.db_path)["fi_stars"], 100)

    def _correct_answer_at(self, challenge, now):
        return rewards.submit_answer(
            42, challenge["token"], challenge["question"]["correct"],
            self.db_path, now=now,
        )

    def test_legacy_user_data_is_preserved_when_wallet_schema_is_added(self):
        with self.database() as db:
            db.execute(
                """
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    xp INTEGER DEFAULT 0,
                    weekly_xp INTEGER DEFAULT 0,
                    week TEXT DEFAULT ''
                )
                """
            )
            db.execute(
                "INSERT INTO users VALUES (42, 'Fan', 75, 15, 'old-week')"
            )

        data = rewards.wallet(42, self.db_path)
        with self.database() as db:
            old_values = db.execute(
                "SELECT xp, weekly_xp FROM users WHERE user_id=42"
            ).fetchone()

        self.assertEqual(old_values, (75, 15))
        self.assertEqual(data["fi_stars"], 0)

    def test_redemption_and_payment_flows_are_disabled(self):
        self.assertFalse(rewards.REDEMPTION_ENABLED)
        self.assertFalse(rewards.CASH_WITHDRAWALS_ENABLED)
        self.assertFalse(rewards.PAYPAL_PAYOUTS_ENABLED)
        self.assertFalse(rewards.TELEGRAM_STARS_LIVE_PAYMENTS_ENABLED)
        self.assertFalse(rewards.TELEGRAM_STARS_TEST_PAYMENTS_ENABLED)

    def test_admin_requires_private_chat_and_allowlisted_user(self):
        allowed = {101}

        self.assertTrue(rewards.admin_access_allowed(101, "private", allowed))
        self.assertFalse(rewards.admin_access_allowed(101, "group", allowed))
        self.assertFalse(rewards.admin_access_allowed(202, "private", allowed))
        self.assertFalse(rewards.admin_access_allowed(None, "private", allowed))


if __name__ == "__main__":
    unittest.main()
