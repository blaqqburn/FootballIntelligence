import hashlib
import hmac
import http.client
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import rewards
from wallet_api import (
    INIT_DATA_MAX_AGE_SECONDS,
    InitDataError,
    create_wallet_app,
    host_origin_matches,
    start_wallet_api,
    verify_init_data,
)


BOT_TOKEN_FOR_TESTS = "test-token-never-used-outside-tests"
AUTH_NOW = 1_800_000_000
APP_ORIGIN = "https://football.example"


def signed_init_data(user_id, auth_date=AUTH_NOW, **extra_fields):
    fields = {
        "auth_date": str(auth_date),
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
    }
    fields.update(extra_fields)
    check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    secret = hmac.new(
        b"WebAppData", BOT_TOKEN_FOR_TESTS.encode(), hashlib.sha256
    ).digest()
    fields["hash"] = hmac.new(
        secret, check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(fields)


class WalletApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = os.path.join(self.directory.name, "wallet.sqlite3")
        self.app = create_wallet_app(
            BOT_TOKEN_FOR_TESTS,
            self.db_path,
            origin=APP_ORIGIN,
            now_fn=lambda: AUTH_NOW,
        )

    def request(self, init_data=None, **overrides):
        environ = {
            "PATH_INFO": "/api/wallet",
            "REQUEST_METHOD": "GET",
            "QUERY_STRING": "",
            "HTTP_ORIGIN": APP_ORIGIN,
            "HTTP_AUTHORIZATION": (
                "tma " + init_data if init_data is not None else ""
            ),
        }
        environ.update(overrides)
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(self.app(environ, start_response))
        captured["body"] = json.loads(body) if body else None
        return captured

    def test_valid_init_data_is_verified_and_user_id_is_signed(self):
        data = signed_init_data(1234)

        self.assertEqual(
            verify_init_data(data, BOT_TOKEN_FOR_TESTS, now=AUTH_NOW),
            1234,
        )

    def test_invalid_signature_and_duplicate_fields_are_rejected(self):
        signed = signed_init_data(1234)
        tampered = signed.replace("%7B%22id%22%3A1234%7D", "%7B%22id%22%3A9999%7D")
        with self.assertRaises(InitDataError):
            verify_init_data(tampered, BOT_TOKEN_FOR_TESTS, now=AUTH_NOW)

        with self.assertRaises(InitDataError):
            verify_init_data(
                signed + "&auth_date=" + str(AUTH_NOW),
                BOT_TOKEN_FOR_TESTS,
                now=AUTH_NOW,
            )

    def test_expired_future_and_malformed_auth_data_are_rejected(self):
        expired = signed_init_data(
            1234, auth_date=AUTH_NOW - INIT_DATA_MAX_AGE_SECONDS - 1
        )
        future = signed_init_data(1234, auth_date=AUTH_NOW + 31)
        malformed_date = signed_init_data(1234, auth_date="not-a-time")
        malformed_user = signed_init_data(1234, user="{")
        boolean_user_id = signed_init_data(True)
        for data in (
            expired,
            future,
            malformed_date,
            malformed_user,
            boolean_user_id,
            "auth_date=broken&user=%7B",
        ):
            with self.subTest(data=data[:20]), self.assertRaises(InitDataError):
                verify_init_data(data, BOT_TOKEN_FOR_TESTS, now=AUTH_NOW)

    def test_wallet_is_bound_to_verified_user_and_returns_ledger(self):
        now = int(time.time())
        challenge = rewards.issue_question(1234, self.db_path, now=now)
        reward = rewards.submit_answer(
            1234,
            challenge["token"],
            challenge["question"]["correct"],
            self.db_path,
            now=now,
        )
        self.assertEqual(reward["status"], "correct")

        response = self.request(signed_init_data(1234))
        other_user = self.request(signed_init_data(5678))

        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(response["body"]["fi_stars"], 10)
        self.assertEqual(response["body"]["weekly_fi_stars"], 10)
        self.assertEqual(response["body"]["history"][0]["amount"], 10)
        self.assertIn("First Goal", response["body"]["badges"])
        self.assertEqual(other_user["body"]["fi_stars"], 0)
        self.assertNotIn("user_id", response["body"])

    def test_authenticated_leaderboard_uses_weekly_ledger_without_user_ids(self):
        now = int(time.time())
        rewards.register_user(1234, "Test fan", self.db_path)
        challenge = rewards.issue_question(1234, self.db_path, now=now)
        result = rewards.submit_answer(
            1234,
            challenge["token"],
            challenge["question"]["correct"],
            self.db_path,
            now=now,
        )
        self.assertEqual(result["status"], "correct")

        response = self.request(
            signed_init_data(1234), PATH_INFO="/api/leaderboard"
        )

        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(
            response["body"]["leaderboard"],
            [{"name": "Test fan", "fi_stars": 10}],
        )
        self.assertNotIn("user_id", response["body"]["leaderboard"][0])

    def test_api_rejects_expired_and_tampered_authentication(self):
        expired = signed_init_data(
            1234, auth_date=AUTH_NOW - INIT_DATA_MAX_AGE_SECONDS - 1
        )
        tampered = signed_init_data(1234).replace(
            "%7B%22id%22%3A1234%7D", "%7B%22id%22%3A5678%7D"
        )

        self.assertEqual(self.request(expired)["status"], "401 Unauthorized")
        self.assertEqual(self.request(tampered)["status"], "401 Unauthorized")

    def test_repeated_read_is_idempotent_and_client_balance_is_rejected(self):
        init_data = signed_init_data(1234)
        first = self.request(init_data)
        second = self.request(init_data)
        with rewards._connection(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM fi_star_transactions WHERE user_id=1234"
            ).fetchone()[0]
            user_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE user_id=1234"
            ).fetchone()[0]

        spoofed = self.request(
            init_data, QUERY_STRING="user_id=5678&fi_stars=999999"
        )

        self.assertEqual(first["body"], second["body"])
        self.assertEqual(count, 0)
        self.assertEqual(user_count, 0)
        self.assertEqual(spoofed["status"], "400 Bad Request")

    def test_api_reads_are_safe_during_duplicate_quiz_submissions(self):
        challenge = rewards.issue_question(1234, self.db_path, now=AUTH_NOW)

        def submit_same_answer():
            return rewards.submit_answer(
                1234,
                challenge["token"],
                challenge["question"]["correct"],
                self.db_path,
                now=AUTH_NOW,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda _: submit_same_answer(), range(2)
            ))
        wallet_response = self.request(signed_init_data(1234))

        self.assertCountEqual(
            [result["status"] for result in results],
            ["correct", "replay"],
        )
        self.assertEqual(wallet_response["body"]["fi_stars"], 10)
        self.assertEqual(len(wallet_response["body"]["history"]), 1)

    def test_missing_auth_method_and_untrusted_origin_are_rejected(self):
        self.assertEqual(self.request()["status"], "401 Unauthorized")
        self.assertEqual(
            self.request(PATH_INFO="/api/leaderboard")["status"],
            "401 Unauthorized",
        )
        preflight = self.request(REQUEST_METHOD="OPTIONS")
        self.assertEqual(preflight["status"], "204 No Content")
        self.assertIsNone(preflight["body"])
        self.assertEqual(
            preflight["headers"]["Access-Control-Allow-Origin"], APP_ORIGIN
        )
        self.assertEqual(
            self.request(
                signed_init_data(1234), REQUEST_METHOD="POST"
            )["status"],
            "405 Method Not Allowed",
        )
        self.assertEqual(
            self.request(
                signed_init_data(1234),
                HTTP_ORIGIN="https://attacker.example",
            )["status"],
            "403 Forbidden",
        )

    def test_origin_matching_normalizes_default_https_port(self):
        self.assertTrue(
            host_origin_matches(
                "https://football.example",
                "https://football.example:443",
            )
        )
        self.assertFalse(
            host_origin_matches(
                "https://football.example",
                "https://football.example:444",
            )
        )

    def test_loopback_http_server_serves_authenticated_wallet(self):
        server, thread = start_wallet_api(
            BOT_TOKEN_FOR_TESTS,
            self.db_path,
            host="127.0.0.1",
            port=0,
        )
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=5
        )
        try:
            connection.request(
                "GET",
                "/api/wallet",
                headers={
                    "Authorization": "tma " + signed_init_data(
                        1234, auth_date=int(time.time())
                    ),
                    "Host": "127.0.0.1",
                },
            )
            response = connection.getresponse()
            body = json.loads(response.read())

            self.assertEqual(response.status, 200)
            self.assertEqual(body["fi_stars"], 0)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
