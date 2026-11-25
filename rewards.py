"""Free quiz rewards and disabled payment foundations for Football Intelligence."""

import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone


DATABASE_PATH = os.environ.get("DATABASE_PATH", "football_intelligence.db")
REWARD_PER_CORRECT_ANSWER = 10
DAILY_EARNING_LIMIT = 100
QUESTION_CHALLENGE_TTL_SECONDS = 10 * 60

# These are display-only proposals. Redemption and all payment flows remain off.
REDEMPTION_ENABLED = False
CASH_WITHDRAWALS_ENABLED = False
PAYPAL_PAYOUTS_ENABLED = False
TELEGRAM_STARS_LIVE_PAYMENTS_ENABLED = False
TELEGRAM_STARS_TEST_PAYMENTS_ENABLED = False
PAYMENT_DESIGN = {
    "telegram_stars_live": {
        "enabled": TELEGRAM_STARS_LIVE_PAYMENTS_ENABLED,
    },
    "paypal_payouts": {
        "purpose": "future approved FI Stars redemptions",
        "enabled": PAYPAL_PAYOUTS_ENABLED,
    },
    "telegram_stars_test": {
        "product": "premium_match_analysis",
        "currency": "XTR",
        "mode": "test_only",
        "enabled": TELEGRAM_STARS_TEST_PAYMENTS_ENABLED,
    },
}
PROVISIONAL_REDEMPTION = {
    "stars_per_euro": 1000,
    "minimum_euro": 5,
    "maximum_euro_per_member_month": 5,
    "pilot_budget_euro_per_month": 20,
}

QUESTIONS = (
    {
        "id": "wc-2022-winner",
        "category": "International",
        "text": "Which country won the 2022 FIFA World Cup?",
        "answers": ("France", "Argentina", "Brazil"),
        "correct": 1,
    },
    {
        "id": "match-duration",
        "category": "Rules",
        "text": "How long is a standard football match, excluding added time?",
        "answers": ("80 minutes", "90 minutes", "100 minutes"),
        "correct": 1,
    },
    {
        "id": "var-meaning",
        "category": "Rules",
        "text": "What does VAR stand for?",
        "answers": (
            "Video Assistant Referee",
            "Virtual Action Replay",
            "Verified Assistant Review",
        ),
        "correct": 0,
    },
    {
        "id": "first-world-cup",
        "category": "History",
        "text": "Which country won the first FIFA World Cup in 1930?",
        "answers": ("Argentina", "Uruguay", "Italy"),
        "correct": 1,
    },
    {
        "id": "world-cup-1966",
        "category": "History",
        "text": "Which nation won the 1966 FIFA World Cup?",
        "answers": ("West Germany", "England", "Brazil"),
        "correct": 1,
    },
    {
        "id": "ucl-2023-winner",
        "category": "Clubs",
        "text": "Which club won the 2023 UEFA Champions League?",
        "answers": ("Inter Milan", "Manchester City", "Real Madrid"),
        "correct": 1,
    },
    {
        "id": "ucl-2008-city",
        "category": "History",
        "text": "In which city was the 2008 UEFA Champions League final played?",
        "answers": ("Moscow", "Rome", "London"),
        "correct": 0,
    },
    {
        "id": "old-trafford",
        "category": "Clubs",
        "text": "Which club plays its home matches at Old Trafford?",
        "answers": ("Liverpool", "Manchester United", "Everton"),
        "correct": 1,
    },
    {
        "id": "premier-league-start",
        "category": "History",
        "text": "In which year did the Premier League begin?",
        "answers": ("1988", "1992", "1996"),
        "correct": 1,
    },
    {
        "id": "most-world-cup-titles",
        "category": "International",
        "text": "Which country has won the most men's FIFA World Cups?",
        "answers": ("Germany", "Brazil", "Italy"),
        "correct": 1,
    },
)

BADGES = (
    (1, "First Goal"),
    (10, "Playmaker"),
    (25, "Golden Boot"),
    (100, "FI Legend"),
)


def _week_key(timestamp=None):
    if timestamp is None:
        timestamp = time.time()
    now = datetime.fromtimestamp(timestamp, timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-{week:02d}"


def _date_key(timestamp=None):
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(
        timestamp, timezone.utc
    ).date().isoformat()


def _ensure_schema(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            xp INTEGER DEFAULT 0,
            weekly_xp INTEGER DEFAULT 0,
            week TEXT DEFAULT ''
        )
        """
    )
    existing = {
        row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "xp" not in existing:
        db.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
    if "weekly_xp" not in existing:
        db.execute(
            "ALTER TABLE users ADD COLUMN weekly_xp INTEGER DEFAULT 0"
        )
    if "week" not in existing:
        db.execute("ALTER TABLE users ADD COLUMN week TEXT DEFAULT ''")
    if "fi_stars" not in existing:
        db.execute(
            "ALTER TABLE users ADD COLUMN fi_stars INTEGER NOT NULL DEFAULT 0"
        )
    if "weekly_fi_stars" not in existing:
        db.execute(
            "ALTER TABLE users ADD COLUMN weekly_fi_stars "
            "INTEGER NOT NULL DEFAULT 0"
        )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS quiz_challenges (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            issued_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            answered_at INTEGER
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            user_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            attempt_date TEXT NOT NULL,
            correct INTEGER NOT NULL,
            attempted_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, question_id, attempt_date)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fi_star_transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            kind TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS earned_badges (
            user_id INTEGER NOT NULL,
            badge_name TEXT NOT NULL,
            earned_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, badge_name)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS suspicious_activity (
            activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payout_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_euro_cents INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            reviewed_at INTEGER
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_records (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            product TEXT NOT NULL,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL,
            external_reference TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )


def connect(db_path=DATABASE_PATH):
    db = sqlite3.connect(db_path, timeout=10)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 10000")
        _ensure_schema(db)
    except Exception:
        db.close()
        raise
    return db


def initialize_database(db_path=DATABASE_PATH):
    db = connect(db_path)
    try:
        db.commit()
    finally:
        db.close()


@contextmanager
def _connection(db_path):
    db = connect(db_path)
    try:
        with db:
            yield db
    finally:
        db.close()


def register_user(user_id, username=None, db_path=DATABASE_PATH):
    now_week = _week_key()
    with _connection(db_path) as db:
        db.execute(
            """
            INSERT OR IGNORE INTO users (user_id, username, week)
            VALUES (?, ?, ?)
            """,
            (user_id, username or "Football fan", now_week),
        )
        if username:
            db.execute(
                "UPDATE users SET username=? WHERE user_id=?",
                (username, user_id),
            )
        db.execute(
            """
            UPDATE users
            SET weekly_xp=0, weekly_fi_stars=0, week=?
            WHERE user_id=? AND week<>?
            """,
            (now_week, user_id, now_week),
        )


def admin_access_allowed(user_id, chat_type, configured_ids):
    return (
        user_id is not None
        and chat_type == "private"
        and user_id in configured_ids
    )


def _record_suspicious(db, user_id, reason, now):
    db.execute(
        """
        INSERT INTO suspicious_activity (user_id, reason, created_at)
        VALUES (?, ?, ?)
        """,
        (user_id, reason, now),
    )


def issue_question(user_id, db_path=DATABASE_PATH, now=None):
    now = int(time.time() if now is None else now)
    register_user(user_id, db_path=db_path)
    with _connection(db_path) as db:
        active = db.execute(
            """
            SELECT question_id, token FROM quiz_challenges
            WHERE user_id=? AND answered_at IS NULL AND expires_at>?
            ORDER BY issued_at DESC LIMIT 1
            """,
            (user_id, now),
        ).fetchone()
        if active:
            question = next(
                item for item in QUESTIONS
                if item["id"] == active["question_id"]
            )
            return {"question": question, "token": active["token"]}

        answered = {
            row[0]
            for row in db.execute(
                """
                SELECT question_id FROM quiz_attempts
                WHERE user_id=? AND attempt_date=?
                """,
                (user_id, _date_key(now)),
            ).fetchall()
        }
        available = [
            item for item in QUESTIONS if item["id"] not in answered
        ]
        if not available:
            return None

        question = secrets.choice(available)
        token = secrets.token_urlsafe(9)
        db.execute(
            """
            INSERT INTO quiz_challenges
                (token, user_id, question_id, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                token,
                user_id,
                question["id"],
                now,
                now + QUESTION_CHALLENGE_TTL_SECONDS,
            ),
        )
        return {"question": question, "token": token}


def submit_answer(user_id, token, choice, db_path=DATABASE_PATH, now=None):
    now = int(time.time() if now is None else now)
    if isinstance(choice, bool) or not isinstance(choice, int):
        return {"status": "invalid"}

    with _connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        challenge = db.execute(
            """
            SELECT question_id, expires_at, answered_at
            FROM quiz_challenges WHERE token=? AND user_id=?
            """,
            (token, user_id),
        ).fetchone()
        if not challenge:
            _record_suspicious(db, user_id, "invalid_quiz_challenge", now)
            return {"status": "invalid"}
        if challenge["answered_at"] is not None:
            _record_suspicious(db, user_id, "replayed_quiz_challenge", now)
            return {"status": "replay"}
        if challenge["expires_at"] <= now:
            _record_suspicious(db, user_id, "expired_quiz_challenge", now)
            return {"status": "expired"}

        question = next(
            (
                item for item in QUESTIONS
                if item["id"] == challenge["question_id"]
            ),
            None,
        )
        if question is None or not 0 <= choice < len(question["answers"]):
            _record_suspicious(db, user_id, "invalid_quiz_answer", now)
            return {"status": "invalid"}

        already_answered = db.execute(
            """
            SELECT 1 FROM quiz_attempts
            WHERE user_id=? AND question_id=? AND attempt_date=?
            """,
            (user_id, question["id"], _date_key(now)),
        ).fetchone()
        if already_answered:
            db.execute(
                "UPDATE quiz_challenges SET answered_at=? WHERE token=?",
                (now, token),
            )
            _record_suspicious(db, user_id, "replayed_quiz_question", now)
            return {"status": "replay"}

        correct = choice == question["correct"]
        db.execute(
            """
            INSERT INTO quiz_attempts
                (user_id, question_id, attempt_date, correct, attempted_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, question["id"], _date_key(now), int(correct), now),
        )
        db.execute(
            "UPDATE quiz_challenges SET answered_at=? WHERE token=?",
            (now, token),
        )
        if not correct:
            return {"status": "incorrect", "awarded": 0}

        # Use the UTC calendar date so the cap resets at UTC midnight.
        start_of_day = int(
            datetime.fromisoformat(_date_key(now))
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        earned_today = db.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM fi_star_transactions
            WHERE user_id=? AND kind='quiz_correct' AND created_at>=?
            """,
            (user_id, start_of_day),
        ).fetchone()[0]
        remaining = max(0, DAILY_EARNING_LIMIT - earned_today)
        awarded = min(REWARD_PER_CORRECT_ANSWER, remaining)
        if awarded == 0:
            return {"status": "daily_limit", "awarded": 0}

        week = _week_key(now)
        db.execute(
            """
            UPDATE users
            SET xp=xp+?, weekly_xp=weekly_xp+?,
                fi_stars=fi_stars+?, weekly_fi_stars=weekly_fi_stars+?,
                week=?
            WHERE user_id=?
            """,
            (REWARD_PER_CORRECT_ANSWER, REWARD_PER_CORRECT_ANSWER,
             awarded, awarded, week, user_id),
        )
        db.execute(
            """
            INSERT INTO fi_star_transactions
                (user_id, amount, kind, created_at)
            VALUES (?, ?, 'quiz_correct', ?)
            """,
            (user_id, awarded, now),
        )
        correct_count = db.execute(
            "SELECT COUNT(*) FROM quiz_attempts "
            "WHERE user_id=? AND correct=1",
            (user_id,),
        ).fetchone()[0]
        new_badges = []
        for threshold, name in BADGES:
            if correct_count >= threshold:
                cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO earned_badges
                        (user_id, badge_name, earned_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, name, now),
                )
                if cursor.rowcount:
                    new_badges.append(name)
        balance = db.execute(
            "SELECT fi_stars FROM users WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        return {
            "status": "correct",
            "awarded": awarded,
            "balance": balance,
            "new_badges": new_badges,
        }


def wallet(user_id, db_path=DATABASE_PATH):
    with _connection(db_path) as db:
        user = db.execute(
            """
            SELECT fi_stars, weekly_fi_stars, week
            FROM users WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()
        if user is None:
            return {
                "fi_stars": 0,
                "weekly_fi_stars": 0,
                "history": [],
                "badges": [],
            }
        history = db.execute(
            """
            SELECT amount, kind, created_at FROM fi_star_transactions
            WHERE user_id=? ORDER BY created_at DESC, transaction_id DESC
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()
        badges = db.execute(
            """
            SELECT badge_name FROM earned_badges
            WHERE user_id=? ORDER BY earned_at
            """,
            (user_id,),
        ).fetchall()
        return {
            "fi_stars": user["fi_stars"],
            "weekly_fi_stars": (
                user["weekly_fi_stars"]
                if user["week"] == _week_key()
                else 0
            ),
            "history": [tuple(row) for row in history],
            "badges": [row[0] for row in badges],
        }


def weekly_leaderboard(db_path=DATABASE_PATH, limit=10):
    with _connection(db_path) as db:
        return [
            tuple(row)
            for row in db.execute(
                """
                SELECT username, weekly_fi_stars FROM users
                WHERE week=? AND weekly_fi_stars>0
                ORDER BY weekly_fi_stars DESC, user_id ASC LIMIT ?
                """,
                (_week_key(), limit),
            ).fetchall()
        ]


def admin_dashboard(db_path=DATABASE_PATH, now=None):
    now = int(time.time() if now is None else now)
    month = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")
    month_start = int(
        datetime.strptime(month, "%Y-%m")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
    with _connection(db_path) as db:
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        star_rewards = db.execute(
            """
            SELECT COALESCE(SUM(amount), 0) FROM fi_star_transactions
            WHERE kind='quiz_correct' AND created_at>=?
            """,
            (month_start,),
        ).fetchone()[0]
        pending_payouts = db.execute(
            "SELECT COUNT(*) FROM payout_requests WHERE status='pending'"
        ).fetchone()[0]
        payment_records = db.execute(
            "SELECT COUNT(*) FROM payment_records"
        ).fetchone()[0]
        suspicious = db.execute(
            "SELECT COUNT(*) FROM suspicious_activity WHERE created_at>=?",
            (now - 7 * 86400,),
        ).fetchone()[0]
        payout_rows = db.execute(
            """
            SELECT request_id, user_id, amount_euro_cents, status, created_at
            FROM payout_requests ORDER BY created_at DESC LIMIT 10
            """
        ).fetchall()
        payment_rows = db.execute(
            """
            SELECT payment_id, user_id, provider, product, amount, currency,
                   status, created_at
            FROM payment_records ORDER BY created_at DESC LIMIT 10
            """
        ).fetchall()
        suspicious_rows = db.execute(
            """
            SELECT user_id, reason, created_at FROM suspicious_activity
            ORDER BY created_at DESC LIMIT 10
            """
        ).fetchall()
        return {
            "users": users,
            "fi_stars_awarded_this_month": star_rewards,
            "pending_payouts": pending_payouts,
            "payment_records": payment_records,
            "suspicious_activity_last_7_days": suspicious,
            "recent_payouts": [tuple(row) for row in payout_rows],
            "recent_payments": [tuple(row) for row in payment_rows],
            "recent_suspicious_activity": [
                tuple(row) for row in suspicious_rows
            ],
        }


def record_suspicious_activity(user_id, reason, db_path=DATABASE_PATH):
    with _connection(db_path) as db:
        _record_suspicious(db, user_id, reason[:80], int(time.time()))
