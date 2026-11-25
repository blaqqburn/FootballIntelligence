"""Authenticated, read-only Telegram Mini App wallet API."""

import hashlib
import hmac
import json
import os
import re
import threading
import time
from socketserver import ThreadingMixIn
from urllib.parse import parse_qsl, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from rewards import wallet, weekly_leaderboard


INIT_DATA_MAX_AGE_SECONDS = 3600
INIT_DATA_FUTURE_SKEW_SECONDS = 30
MAX_INIT_DATA_LENGTH = 8192
WALLET_PATH = "/api/wallet"
LEADERBOARD_PATH = "/api/leaderboard"
FIXTURES_PATH = "/api/fixtures"


class InitDataError(ValueError):
    """Raised when Telegram Mini App initData is invalid or stale."""


def verify_init_data(init_data, bot_token, now=None):
    if not isinstance(init_data, str) or not init_data:
        raise InitDataError("Missing Telegram authentication data.")
    if len(init_data) > MAX_INIT_DATA_LENGTH:
        raise InitDataError("Telegram authentication data is too large.")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not configured.")

    try:
        fields = parse_qsl(
            init_data,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=50,
        )
    except ValueError as exc:
        raise InitDataError("Malformed Telegram authentication data.") from exc

    values = {}
    for key, value in fields:
        if key in values:
            raise InitDataError("Duplicate Telegram authentication field.")
        values[key] = value

    supplied_hash = values.pop("hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", supplied_hash):
        raise InitDataError("Invalid Telegram authentication signature.")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise InitDataError("Invalid Telegram authentication signature.")

    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InitDataError(
            "Required Telegram authentication fields are invalid."
        ) from exc

    if isinstance(user, dict):
        user_id = user.get("id")
    else:
        user_id = None
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise InitDataError("Authenticated Telegram user is invalid.")

    current_time = int(time.time() if now is None else now)
    if auth_date > current_time + INIT_DATA_FUTURE_SKEW_SECONDS:
        raise InitDataError("Telegram authentication data is from the future.")
    if current_time - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        raise InitDataError("Telegram authentication data has expired.")

    return user_id


def _json_response(start_response, status, payload, headers=None):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    response_headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
        ("Pragma", "no-cache"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
    ]
    if headers:
        response_headers.extend(headers)
    start_response(status, response_headers)
    return [body]


def _empty_response(start_response, status, headers=None):
    response_headers = [
        ("Content-Length", "0"),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
    ]
    if headers:
        response_headers.extend(headers)
    start_response(status, response_headers)
    return [b""]


def _allowed_origin(environ, configured_origin):
    origin = environ.get("HTTP_ORIGIN")
    if not origin:
        return None
    if configured_origin:
        expected = configured_origin
    else:
        host = environ.get("HTTP_HOST", "")
        scheme = environ.get("wsgi.url_scheme", "https")
        expected = f"{scheme}://{host}"
    if not host_origin_matches(origin, expected):
        return False
    return origin


def host_origin_matches(origin, expected):
    try:
        parsed = urlsplit(origin)
        expected_parsed = urlsplit(expected)
        origin_host = parsed.hostname
        expected_host = expected_parsed.hostname
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        expected_port = expected_parsed.port or (
            443 if expected_parsed.scheme == "https" else 80
        )
    except ValueError:
        return False
    return bool(
        parsed.scheme in ("https", "http")
        and origin_host
        and expected_host
        and parsed.username is None
        and parsed.password is None
        and parsed.scheme == expected_parsed.scheme
        and origin_host.lower() == expected_host.lower()
        and origin_port == expected_port
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and not expected_parsed.path
        and not expected_parsed.query
        and not expected_parsed.fragment
        and expected_parsed.username is None
        and expected_parsed.password is None
    )


def create_wallet_app(bot_token, db_path, origin=None, now_fn=None):
    """Build authenticated, read-only wallet and leaderboard API routes."""
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not configured.")
    now_fn = now_fn or time.time
    configured_origin = origin or os.environ.get("MINIAPP_ORIGIN")

    def app(environ, start_response):
        request_path = environ.get("PATH_INFO", "")
        if request_path not in (WALLET_PATH, LEADERBOARD_PATH, FIXTURES_PATH):
            return _json_response(
                start_response, "404 Not Found", {"error": "Not found."}
            )
        if environ.get("QUERY_STRING"):
            return _json_response(
                start_response,
                "400 Bad Request",
                {"error": "Query parameters are not accepted."},
            )

        request_origin = _allowed_origin(environ, configured_origin)
        if request_origin is False:
            return _json_response(
                start_response, "403 Forbidden", {"error": "Origin denied."}
            )
        cors_headers = []
        if request_origin:
            cors_headers.extend(
                [
                    ("Access-Control-Allow-Origin", request_origin),
                    ("Vary", "Origin"),
                ]
            )

        method = environ.get("REQUEST_METHOD", "GET").upper()
        if method == "OPTIONS":
            return _empty_response(
                start_response,
                "204 No Content",
                cors_headers
                + [
                    ("Access-Control-Allow-Methods", "GET, OPTIONS"),
                    ("Access-Control-Allow-Headers", "Authorization"),
                    ("Access-Control-Max-Age", "300"),
                ],
            )
        if method != "GET":
            return _json_response(
                start_response,
                "405 Method Not Allowed",
                {"error": "Method not allowed."},
                cors_headers + [("Allow", "GET, OPTIONS")],
            )

        if request_path == FIXTURES_PATH:
            try:
                from miniapp_fixtures import get_fixture_data
                return _json_response(
                    start_response, "200 OK",
                    get_fixture_data(), cors_headers
                )
            except Exception:
                return _json_response(
                    start_response, "503 Service Unavailable",
                    {"error": "Football fixtures temporarily unavailable."},
                    cors_headers
                )

        authorization = environ.get("HTTP_AUTHORIZATION", "")
        if not authorization.startswith("tma "):
            return _json_response(
                start_response,
                "401 Unauthorized",
                {"error": "Telegram authentication is required."},
                cors_headers + [("WWW-Authenticate", "tma")],
            )
        try:
            user_id = verify_init_data(
                authorization[4:], bot_token, now=int(now_fn())
            )
            if request_path == WALLET_PATH:
                account = wallet(user_id, db_path)
                payload = {
                    "fi_stars": account["fi_stars"],
                    "weekly_fi_stars": account["weekly_fi_stars"],
                    "history": [
                        {
                            "amount": amount,
                            "kind": kind,
                            "created_at": created_at,
                        }
                        for amount, kind, created_at in account["history"]
                    ],
                    "badges": account["badges"],
                }
            else:
                payload = {
                    "leaderboard": [
                        {"name": name, "fi_stars": points}
                        for name, points in weekly_leaderboard(db_path)
                    ]
                }
        except InitDataError:
            return _json_response(
                start_response,
                "401 Unauthorized",
                {"error": "Telegram authentication is invalid or expired."},
                cors_headers + [("WWW-Authenticate", "tma")],
            )

        return _json_response(start_response, "200 OK", payload, cors_headers)

    return app


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietRequestHandler(WSGIRequestHandler):
    def log_message(self, format_string, *args):
        pass


def start_wallet_api(
    bot_token, db_path, host="127.0.0.1", port=8080, origin=None
):
    """Start the API in a daemon thread; terminate TLS at a trusted proxy."""
    app = create_wallet_app(bot_token, db_path, origin=origin)
    server = make_server(
        host,
        port,
        app,
        server_class=ThreadedWSGIServer,
        handler_class=QuietRequestHandler,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="fi-wallet-api",
        daemon=True,
    )
    thread.start()
    return server, thread
