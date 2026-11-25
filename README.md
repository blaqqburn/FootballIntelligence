# Football Intelligence

Football Intelligence is a Telegram bot with a companion mini app for football-related information.

## Free quizzes and FI Stars

Quizzes are free to enter and never require a purchase, deposit, or membership. Correct answers award 10 FI Stars, capped at 100 per user per UTC day. Each question can be attempted once per account per UTC day. Challenges are short-lived and user-bound; invalid, expired, and replayed attempts are recorded for review. FI Stars have a separate wallet and transaction history, weekly leaderboard, and milestone badges. They are not official Telegram Stars.

The Mini App quiz offers local practice only. Its account wallet display is synchronized through the authenticated read-only API below; browser-side practice scores are not submitted as rewards.

## Payments and redemption

Proposed values are display-only: 5,000 FI Stars = €5, a €5 minimum, a €5 monthly maximum per eligible member, and a €20 monthly pilot budget. These values are provisional, not guaranteed cash entitlements. Redemption and PayPal payouts are hard-disabled. No payout request or live payment flow is available. Activation requires legal approval, payment-provider approval, and confirmed reward funding.

The database has records for future payout requests and payment events. The private `/admin` dashboard is restricted to numeric Telegram user IDs listed in `BOT_ADMIN_IDS` and only responds in private chats. It summarizes reward activity, pending requests, payment records, and suspicious events. No PayPal credentials are requested or used. Telegram Stars test-payment preparation is inactive and no invoice is sent.

## Running and testing

Set `FI_ENV=production` and `BOT_TOKEN` in the process environment to run the production bot. Development runs require `FI_ENV=development`, `FI_TEST_BOT_TOKEN`, and `FI_TEST_BOT_USERNAME`; in development, the application never reads or falls back to `BOT_TOKEN`, and verifies Telegram's `getMe` username before initializing the database, wallet API, or polling. Unknown or missing `FI_ENV` fails closed. Optionally set `BOT_ADMIN_IDS` to a comma-separated allowlist, `DATABASE_PATH` to select the SQLite file, and `WALLET_API_HOST` / `WALLET_API_PORT` to configure the local API listener (defaults: `127.0.0.1:8080`). Set `MINIAPP_URL` to the Mini App's HTTPS URL to add its Telegram launch button; `MINIAPP_ORIGIN` must match its exact origin if set. Never commit tokens, API credentials, local environment files, database files, or virtual environments.

The reward ledger uses additive SQLite schema changes to preserve existing user data. Focused standard-library tests are in `tests/test_rewards.py`; run them with `python -m unittest discover -s tests`.

### Windows PowerShell tests

Run these commands from PowerShell. They set the working directory to this isolated branch, while using the existing local venv's interpreter without installing packages. The reward tests create temporary SQLite databases and do not open the project database.

```powershell
Set-Location -LiteralPath 'C:\Users\kwe_b\.copilot\repos\copilot-worktrees\FootballIntelligence\blaqqburn-special-umbrella'
$Python = 'C:\Users\kwe_b\Documents\FootballIntelligence\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'The existing Python interpreter was not found.' }

& $Python -B -c "from pathlib import Path; files = ['bot.py', 'bot_config.py', 'rewards.py', 'wallet_api.py', 'tests/test_bot_config.py', 'tests/test_rewards.py', 'tests/test_wallet_api.py']; [compile(Path(file).read_text(encoding='utf-8'), file, 'exec') for file in files]"
if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed.' }

& $Python -B -m unittest discover -s .\tests -v
if ($LASTEXITCODE -ne 0) { throw 'Reward tests failed.' }
```

The syntax check and tests use only Python's standard library. Running the Telegram bot itself also requires the `python-telegram-bot` package; this repository does not include a dependency manifest.

### Development test bot

Create a separate bot with Telegram's official bot-management flow and use its username and token only for development. Provision `FI_TEST_BOT_TOKEN` in the current PowerShell process through your approved secret manager or the secure prompt below; do not paste it into a command, source file, `.env` file, or this repository. Development mode selects only `FI_TEST_BOT_TOKEN` and `FI_TEST_BOT_USERNAME`; an inherited production `BOT_TOKEN` is ignored. Before any database/API/polling startup, `getMe` must return the configured test username or startup stops with a redacted error. No live bot check is performed by the automated tests.

```powershell
$Repo = 'C:\Users\kwe_b\.copilot\repos\copilot-worktrees\FootballIntelligence\blaqqburn-special-umbrella'
$Python = 'C:\Users\kwe_b\Documents\FootballIntelligence\.venv\Scripts\python.exe'
$secureToken = Read-Host 'Separate test bot token' -AsSecureString
$env:FI_TEST_BOT_TOKEN = [System.Net.NetworkCredential]::new('', $secureToken).Password
$secureToken = $null
$env:FI_TEST_BOT_USERNAME = 'your_separate_test_bot' # Replace with the separate bot's exact username.
$env:FI_ENV = 'development'
$env:DATABASE_PATH = Join-Path $Repo 'football_intelligence_e2e.sqlite3'
$env:WALLET_API_HOST = '127.0.0.1'
$env:WALLET_API_PORT = '8080'
$env:MINIAPP_ORIGIN = 'https://<reserved-test-host>'
$env:MINIAPP_URL = "$env:MINIAPP_ORIGIN/"
Set-Location -LiteralPath $Repo
if (-not $env:FI_TEST_BOT_TOKEN) { throw 'Test bot token was not provided.' }
& $Python -B .\bot.py
```

The secure prompt prevents the token from appearing in command history or terminal output, but the running process necessarily holds it in memory. Keep the token scoped to this test process and clear it from the shell environment after stopping the bot with `$env:FI_TEST_BOT_TOKEN = $null`. The startup check contacts Telegram's `getMe` endpoint for the separate test bot; automated checks do not contact Telegram. Use a reserved HTTPS development host whose reverse proxy sends `/api/wallet` to `127.0.0.1:8080` and other paths to the static server on `127.0.0.1:8000`. Keep both local servers loopback-only, rate-limit requests, disable API caching, and redact `Authorization` headers.

### Mini App wallet API

The bot starts authenticated, read-only `/api/wallet` and `/api/leaderboard` endpoints on `127.0.0.1:8080` by default. Configure `MINIAPP_URL` to the Mini App's HTTPS URL; the bot then adds a Telegram Web App button. Serve the Mini App and proxy both same-origin API paths over HTTPS to the local API (the Python API listener itself is not TLS-enabled). Set `MINIAPP_ORIGIN` to the exact HTTPS origin. Keep the API bound to loopback behind that proxy, apply request rate limits, disable caching, and redact `Authorization` headers from proxy logs.

Both endpoints validate Telegram `initData` HMAC using the token selected for the explicitly configured environment and accept authentication data for at most one hour. `/api/wallet` derives its user ID only from verified Telegram data and returns that user's balance, history, and badges from the bot's SQLite ledger. `/api/leaderboard` returns the existing public weekly leaderboard; neither endpoint accepts client-supplied identity, score, balance, or mutation parameters. Repeating an authenticated GET is safe and read-only; it does not earn rewards. Bot quiz rewards continue to use their existing expiring, user-bound challenges and atomic duplicate-attempt protections. If Telegram authentication is missing or stale, reopen the Mini App from Telegram.

The Rewards view displays the authenticated wallet balance, weekly personal total, transactions, badges, and weekly leaderboard. Its home tile says “FI Stars wallet and leaderboard”; the page loads `/api/wallet` and `/api/leaderboard`. The old “Your XP and weekly ranking will appear here” and “Telegram account integration is coming next” copy is not in this branch's Mini App HTML. If those exact strings appear, the opened Mini App is served from a stale/different HTML file or cached launch URL, rather than from this checked-in version. The Mini App displays practice quizzes locally and browser-side practice scores are never submitted as rewards. Do not enable client-authoritative wallet changes or connect PayPal, cash withdrawals, or Telegram Stars payments.

### Local Windows end-to-end test checklist (not started)

Use only the separate development bot and a test Telegram account. The bot process starts the wallet API itself on `127.0.0.1:8080`; do not launch a second API process. The API and bot share `DATABASE_PATH`, which must point to a new ignored SQLite file inside this worktree. Never use the original project's database or production bot credentials.

First, start a loopback-only static server in one PowerShell window:

```powershell
$Repo = 'C:\Users\kwe_b\.copilot\repos\copilot-worktrees\FootballIntelligence\blaqqburn-special-umbrella'
$Python = 'C:\Users\kwe_b\Documents\FootballIntelligence\.venv\Scripts\python.exe'
Set-Location -LiteralPath (Join-Path $Repo 'miniapp')
& $Python -B -m http.server 8000 --bind 127.0.0.1
```

Use a trusted HTTPS development tunnel/reverse proxy with a reserved hostname. Route both `/api/wallet` and `/api/leaderboard` to `http://127.0.0.1:8080`; route other paths on that same origin to `http://127.0.0.1:8000/`. Keep both local listeners loopback-only, preserve the browser `Origin`, apply rate limits, disable caching for API responses, and redact `Authorization` headers from logs. A simple single-origin tunnel without path-based upstream routing is insufficient. The tunnel provider/hostname is not selected here, so no provider-specific tunnel command is included.

Before starting the test bot, use a versioned launch URL to bypass a previously cached Mini App document. Keep `MINIAPP_ORIGIN` set to the bare HTTPS origin; add the cache-busting query only to `MINIAPP_URL`:

```powershell
$env:MINIAPP_ORIGIN = 'https://<reserved-test-host>'
$env:MINIAPP_URL = "$env:MINIAPP_ORIGIN/?v=fi-wallet-v2"
```

In the static-server window, verify the served file directly without opening or reading any database or credential:

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing |
  Select-Object -ExpandProperty Content |
  Select-String -Pattern 'FI Stars wallet and leaderboard|walletLeaderboard|/api/leaderboard'
```

All three markers should be present. If not, the static server's working directory is not this branch's `miniapp` folder. Then open the test bot's `/start` menu and launch the Mini App. Fully close any already-open Mini App instance before reopening the new versioned link. In a private chat with the test bot, send `/start`, open its Mini App button, and check each item below:

1. **Free quiz rewards:** answer one bot quiz correctly; expect +10 FI Stars and a matching ledger transaction.
2. **Replay and daily limit:** replay the same callback/question and confirm no duplicate award; continue with fresh questions and verify the daily maximum remains 100 FI Stars per UTC day. Wrong answers do not award Stars.
3. **Wallet/history:** refresh the Mini App Rewards view and confirm balance and transaction history match the bot wallet in the same branch-local database.
4. **Leaderboard/badges:** check that earned points appear in the Mini App weekly leaderboard and bot leaderboard, and that the corresponding milestone badge appears in the wallet.
5. **Account sync/isolation:** open the Mini App as the same test Telegram account; authenticated wallet data should match that account only. The local browser practice quiz score must not affect FI Stars.
6. **Mutation denial:** browser requests with client-supplied wallet parameters or a POST must not change the ledger. The following probes should return `400` and `405` respectively:

```javascript
fetch("/api/wallet?user_id=1&fi_stars=999999").then(response => response.status)
fetch("/api/wallet", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ fi_stars: 999999 })
}).then(response => response.status)
```

Before attempting the checklist, confirm `python-telegram-bot` is installed in the selected existing venv, ports 8000/8080 are free, the reserved HTTPS hostname is configured in both `MINIAPP_URL` (with the `?v=fi-wallet-v2` cache-buster) and bare `MINIAPP_ORIGIN`, and the tunnel supports all three same-origin routes above. In Telegram, if the old placeholder still appears after reopening the versioned URL, verify the bot's actual Web App button URL and the reverse proxy's static upstream; that content is not present in this branch's `miniapp/index.html`. The app deliberately keeps local practice quiz XP separate from real FI Stars. No cash, withdrawal, PayPal, or Telegram Stars payment path is active.

The Mini App uses safe-area-aware spacing, responsive mobile sizing, larger navigation touch targets, visible keyboard focus, active-page navigation state, and an explicit wallet refresh button. These are presentation/usability changes only; quiz and reward rules are unchanged.
