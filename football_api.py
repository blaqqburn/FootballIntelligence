import os
import time
from datetime import datetime, timedelta, timezone
import requests

API_URL = "https://v3.football.api-sports.io"
_cache = {"expires": 0, "text": ""}

LIVE = {"1H", "2H", "HT", "ET", "BT", "P", "INT", "LIVE"}
UPCOMING = {"NS", "TBD"}

def get_today_fixtures(limit=10):
    now = datetime.now(timezone.utc)

    if time.time() < _cache["expires"]:
        return _cache["text"]

    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        return "Football API key is not configured."

    try:
        matches = []
        for day in (now.date(), (now + timedelta(days=1)).date()):
            response = requests.get(
                f"{API_URL}/fixtures",
                headers={"x-apisports-key": key},
                params={"date": day.isoformat()},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                return "Football data is temporarily unavailable."
            matches.extend(data.get("response", []))

        live, upcoming = [], []

        for match in matches:
            fixture = match["fixture"]
            status = fixture["status"]["short"]
            kickoff = datetime.fromisoformat(
                fixture["date"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)

            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            league = match["league"]["name"]
            local_time = kickoff.astimezone().strftime("%d %b %H:%M")

            if status in LIVE:
                goals = match["goals"]
                score = f'{goals["home"]}-{goals["away"]}'
                live.append((kickoff, f"{home} {score} {away}\n🏆 {league} | LIVE"))
            elif status in UPCOMING and now <= kickoff < now + timedelta(hours=24):
                upcoming.append(
                    (kickoff, f"{home} vs {away}\n🕒 {local_time} | {league}")
                )

        live.sort(key=lambda x: x[0])
        upcoming.sort(key=lambda x: (
    not any(name in x[1].lower() for name in (
        "champions league",
        "europa league",
        "premier league",
        "bundesliga",
        "la liga",
        "serie a",
        "ligue 1"
    )),
    x[0]
))

        lines = ["⚽ FOOTBALL INTELLIGENCE\n"]
        lines.append("🔴 LIVE NOW")
        lines.extend(item[1] for item in live[:limit])
        if not live:
            lines.append("No matches currently live.")

        lines.append("\n🕒 NEXT 24 HOURS")
        lines.extend(item[1] for item in upcoming[:limit])
        if not upcoming:
            lines.append("No upcoming fixtures found.")

        result = "\n\n".join(lines)
        _cache.update(expires=time.time() + 300, text=result)
        return result

    except (requests.RequestException, ValueError, KeyError, TypeError):
        return "Unable to retrieve football fixtures right now."
