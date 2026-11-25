
import asyncio
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit

from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from rewards import (
    CASH_WITHDRAWALS_ENABLED,
    DAILY_EARNING_LIMIT,
    PAYMENT_DESIGN,
    PAYPAL_PAYOUTS_ENABLED,
    PROVISIONAL_REDEMPTION,
    REDEMPTION_ENABLED,
    TELEGRAM_STARS_TEST_PAYMENTS_ENABLED,
    TELEGRAM_STARS_LIVE_PAYMENTS_ENABLED,
    admin_access_allowed,
    admin_dashboard,
    issue_question,
    initialize_database,
    record_suspicious_activity,
    register_user,
    submit_answer,
    wallet,
    weekly_leaderboard,
)
from bot_config import (
    load_bot_configuration,
    verify_development_bot,
)
from wallet_api import start_wallet_api

DB = os.environ.get("DATABASE_PATH", "football_intelligence.db")


def miniapp_configuration():
    miniapp_url = os.environ.get("MINIAPP_URL", "").strip()
    if not miniapp_url:
        return "", os.environ.get("MINIAPP_ORIGIN")

    parsed_url = urlsplit(miniapp_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.fragment
    ):
        raise RuntimeError("MINIAPP_URL must be an absolute HTTPS URL.")

    expected_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    configured_origin = os.environ.get("MINIAPP_ORIGIN", expected_origin)
    if configured_origin != expected_origin:
        raise RuntimeError(
            "MINIAPP_ORIGIN must match the origin in MINIAPP_URL."
        )
    return miniapp_url, expected_origin


@contextmanager
def database():
    initialize_database(DB)
    db = sqlite3.connect(DB)
    try:
        with db:
            yield db
    finally:
        db.close()

def register(user):
    register_user(user.id, user.username or user.first_name, DB)

def menu():
    miniapp_url, _ = miniapp_configuration()
    web_app_button = None
    if miniapp_url:
        web_app_button = InlineKeyboardButton(
            "🌐 Open FI Mini App", web_app=WebAppInfo(url=miniapp_url)
        )

    buttons = [
        [InlineKeyboardButton("⚽ Fixtures & Live", callback_data="matches")],
        [InlineKeyboardButton("📊 Match Analysis", callback_data="analysis")],
        [InlineKeyboardButton("🧠 Football Quiz", callback_data="quiz")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("⭐ FI Stars Wallet", callback_data="rewards")],
        [InlineKeyboardButton("🔒 Premium Intelligence", callback_data="premium")],
        [InlineKeyboardButton("🎯 Potential Winnings", callback_data="winnings")]
    ]
    if web_app_button:
        buttons.insert(0, [web_app_button])
    return InlineKeyboardMarkup(buttons)

def back():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register(update.effective_user)
    await update.message.reply_text(
        "⚽🏆 WELCOME TO FOOTBALL INTELLIGENCE!\n\n"
        "KNOW THE GAME. READ THE DATA.\n\n"
        "Your football hub for live scores, upcoming fixtures, "
        "match intelligence, quizzes and FI Stars.\n\n"
        "🧠 OUR FOOTBALL INTELLIGENCE ENGINE\n"
        "We connect to professional football-data services to "
        "bring real match information into your Telegram experience.\n\n"
        "📊 Explore statistics and match trends.\n"
        "⚽ Follow live and upcoming fixtures.\n"
        "🏆 Play quizzes and earn FI Stars.\n"
        "🔐 Premium Intelligence is coming soon.\n\n"
        "💡 BET SMARTER, NOT BIGGER.\n"
        "Check the data, compare the odds and set a budget.\n"
        "Predictions are never guaranteed. Never chase losses.\n\n"
        "👇 Choose a feature to begin:",
        reply_markup=menu()
    )

async def send_quiz(query, context):
    challenge = issue_question(query.from_user.id, DB)
    if challenge is None:
        await query.edit_message_text(
            "🏁 You've answered every available question. "
            "New questions will be added later.\n\n"
            "Each question can earn FI Stars only once per UTC day.",
            reply_markup=back()
        )
        return

    question = challenge["question"]
    buttons = [
        [
            InlineKeyboardButton(
                answer,
                callback_data=f"quiz_answer:{challenge['token']}:{i}"
            )
        ]
        for i, answer in enumerate(question["answers"])
    ]
    await query.edit_message_text(
        f"🧠 FREE QUIZ • {question['category']}\n\n{question['text']}\n\n"
        f"Correct answers earn 10 FI Stars, up to "
        f"{DAILY_EARNING_LIMIT} per UTC day.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user = update.effective_user
    register(user)

    if action == "home":
        await query.edit_message_text(
            "⚽ FOOTBALL INTELLIGENCE\n\nChoose a feature:",
            reply_markup=menu()
        )

    elif action == "quiz":
        await send_quiz(query, context)

    elif action.startswith("quiz_answer:"):
        parts = action.split(":")
        try:
            if len(parts) != 3:
                raise ValueError
            choice = int(parts[2])
        except ValueError:
            record_suspicious_activity(user.id, "malformed_quiz_callback", DB)
            await query.edit_message_text(
                "That quiz answer is invalid. Start a new question.",
                reply_markup=back()
            )
            return

        result = submit_answer(user.id, parts[1], choice, DB)
        if result["status"] == "correct":
            message = f"✅ Correct! +{result['awarded']} FI Stars."
            if result["new_badges"]:
                message += "\n🎖 New badge: " + ", ".join(
                    result["new_badges"]
                )
        elif result["status"] == "incorrect":
            message = "❌ Incorrect. This question cannot be replayed today."
        elif result["status"] == "daily_limit":
            message = "✅ Correct, but your daily FI Stars limit is reached."
        elif result["status"] == "replay":
            message = "This question has already been answered."
        elif result["status"] == "expired":
            message = "This quiz question expired. Start a new question."
        else:
            message = "That quiz answer is invalid. Start a new question."

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "➡️ Next Question", callback_data="quiz"
                )]
            ])
        )

    elif action == "rewards":
        data = wallet(user.id, DB)
        history = [
            f"• {amount:+} FI Stars — {kind.replace('_', ' ')} "
            f"({datetime.fromtimestamp(created_at, timezone.utc):%Y-%m-%d})"
            for amount, kind, created_at in data["history"]
        ]
        badges = ", ".join(data["badges"]) if data["badges"] else "None yet"
        history_text = "\n".join(history) if history else "No transactions yet."

        await query.edit_message_text(
            f"⭐ FI STARS WALLET\n\n"
            f"Balance: {data['fi_stars']} FI Stars\n"
            f"This week: {data['weekly_fi_stars']} FI Stars\n"
            f"Official Telegram Stars: separate and unaffected\n\n"
            f"🎖 Achievements: {badges}\n\n"
            f"🧾 Recent history:\n{history_text}\n\n"
            "FI Stars are free, non-transferable quiz points; they are "
            "not official Telegram Stars or guaranteed cash.\n\n"
            "Proposed cash values are provisional and redemption is disabled.",
            reply_markup=back()
        )

    elif action == "leaderboard":
        rows = weekly_leaderboard(DB)

        lines = ["🏆 WEEKLY LEADERBOARD\n"]
        for i, (name, points) in enumerate(rows, 1):
            lines.append(f"{i}. {name} — {points} FI Stars")

        if not rows:
            lines.append("No quiz scores yet!")

        await query.edit_message_text(
            "\n".join(lines), reply_markup=back()
        )

    elif action == "premium":
        await query.edit_message_text(
            "🔒 PREMIUM INTELLIGENCE\n\n"
            "🔐 Match outcome probabilities\n"
            "🔐 Potential corners\n"
            "🔐 Free-kick estimates\n"
            "🔐 Player goalscorer analysis\n"
            "🔐 Advanced match statistics\n"
            "🔐 Prediction performance history\n\n"
            "Premium reports are not available for purchase yet.\n"
            f"Test-payment design: {PAYMENT_DESIGN['telegram_stars_test']['product']} "
            f"using {PAYMENT_DESIGN['telegram_stars_test']['currency']} in "
            "test-only mode. It is inactive; no invoice or charge is sent.\n"
            "All predictions will be estimates, not guarantees.",
            reply_markup=back()
        )

    elif action == "matches":
        import asyncio
        from football_api import get_today_fixtures

        fixtures_text = await asyncio.to_thread(get_today_fixtures)
        await query.edit_message_text(
            fixtures_text,
            reply_markup=back()
        )

    elif action == "analysis":
        import asyncio
        from match_analysis import get_match_analysis

        analysis_text = await asyncio.to_thread(get_match_analysis)
        await query.edit_message_text(
            analysis_text,
            reply_markup=back()
        )
    elif action == "winnings":
        context.user_data["awaiting_odds"] = True
        await query.edit_message_text(
            "🎯 POTENTIAL WINNINGS CALCULATOR\n\n"
            "Enter your stake and decimal odds separated by a space.\n\n"
            "Example: 5 2.50\n\n"
            "This calculates hypothetical returns, not a prediction.",
            reply_markup=back()
        )

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_odds"):
        return

    try:
        values = update.message.text.replace(",", ".").split()
        if len(values) != 2:
            raise ValueError()

        stake, odds = map(float, values)

        if not (0 < stake <= 100000 and 1 < odds <= 10000):
            raise ValueError()

        payout = stake * odds
        profit = payout - stake
        probability = 100 / odds

        context.user_data["awaiting_odds"] = False

        await update.message.reply_text(
            f"🎯 POTENTIAL WINNINGS\n\n"
            f"Stake: €{stake:.2f}\n"
            f"Decimal odds: {odds:.2f}\n"
            f"Potential payout: €{payout:.2f}\n"
            f"Potential net profit: €{profit:.2f}\n"
            f"Break-even probability: {probability:.1f}%\n\n"
            "If the selection loses, the entire stake may be lost. "
            "Calculations exclude fees and special settlement rules.",
            reply_markup=back()
        )

    except ValueError:
        await update.message.reply_text(
            "Please enter two valid numbers, e.g. 5 2.50"
        )

def admin_ids():
    ids = set()
    for value in os.environ.get("BOT_ADMIN_IDS", "").split(","):
        value = value.strip()
        if value.isdecimal() and int(value) > 0:
            ids.add(int(value))
    return ids


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or chat.type != "private":
        if user:
            record_suspicious_activity(
                user.id, "admin_dashboard_non_private_access", DB
            )
        return
    if not admin_access_allowed(user.id, chat.type, admin_ids()):
        record_suspicious_activity(
            user.id, "unauthorized_admin_dashboard_access", DB
        )
        await update.message.reply_text("Administrator access denied.")
        return

    data = admin_dashboard(DB)
    redemption = PROVISIONAL_REDEMPTION
    payouts = "\n".join(
        f"#{request_id} • user {user_id} • €{amount_cents / 100:.2f} "
        f"• {status}"
        for request_id, user_id, amount_cents, status, _ in data["recent_payouts"]
    ) or "None"
    payments = "\n".join(
        f"#{payment_id} • user {user_id} • {provider}/{product} "
        f"• {amount} {currency} • {status}"
        for (
            payment_id, user_id, provider, product, amount, currency,
            status, _
        ) in data["recent_payments"]
    ) or "None"
    suspicious = "\n".join(
        f"user {user_id or 'unknown'} • {reason}"
        for user_id, reason, _ in data["recent_suspicious_activity"]
    ) or "None"
    await update.message.reply_text(
        "🔒 PRIVATE ADMIN DASHBOARD\n\n"
        f"Users: {data['users']}\n"
        f"FI Stars awarded this month: "
        f"{data['fi_stars_awarded_this_month']}\n"
        f"Pending payout requests: {data['pending_payouts']}\n"
        f"Payment records: {data['payment_records']}\n"
        f"Suspicious events (7 days): "
        f"{data['suspicious_activity_last_7_days']}\n\n"
        f"Recent payout requests:\n{payouts}\n\n"
        f"Recent payment records:\n{payments}\n\n"
        f"Recent suspicious activity:\n{suspicious}\n\n"
        "Provisional redemption proposal (not an entitlement): "
        f"{redemption['stars_per_euro'] * 5:,} FI Stars = €5; "
        f"minimum €{redemption['minimum_euro']}; "
        f"maximum €{redemption['maximum_euro_per_member_month']} "
        "per eligible member/month; "
        f"pilot budget €{redemption['pilot_budget_euro_per_month']}/month; "
        "confirmed funding: none.\n"
        f"Redemption: {'ENABLED' if REDEMPTION_ENABLED else 'DISABLED'}\n"
        f"Cash withdrawals: "
        f"{'ENABLED' if CASH_WITHDRAWALS_ENABLED else 'DISABLED'}\n"
        f"PayPal payouts: {'ENABLED' if PAYPAL_PAYOUTS_ENABLED else 'DISABLED'}\n"
        f"Telegram Stars live payments: "
        f"{'ENABLED' if TELEGRAM_STARS_LIVE_PAYMENTS_ENABLED else 'DISABLED'}\n"
        f"Telegram Stars test payments: "
        f"{'ENABLED' if TELEGRAM_STARS_TEST_PAYMENTS_ENABLED else 'DISABLED'}\n\n"
        "No redemption or payment operation is available. Activation "
        "requires legal approval, payment-provider approval and confirmed "
        "reward funding.",
    )


def main():
    configuration = load_bot_configuration()
    token = configuration.token
    if configuration.environment == "development":
        asyncio.run(verify_development_bot(
            token, configuration.expected_username, Bot
        ))

    with database():
        pass

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, messages)
    )

    api_host = os.environ.get("WALLET_API_HOST", "127.0.0.1")
    api_port = int(os.environ.get("WALLET_API_PORT", "8080"))
    _, miniapp_origin = miniapp_configuration()
    wallet_server, wallet_thread = start_wallet_api(
        token, DB, host=api_host, port=api_port, origin=miniapp_origin
    )
    print("Football Intelligence v0.2 is running...")
    try:
        app.run_polling()
    finally:
        wallet_server.shutdown()
        wallet_server.server_close()
        wallet_thread.join()

if __name__ == "__main__":
    main()

