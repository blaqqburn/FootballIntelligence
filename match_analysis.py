import os
import requests

API_URL = "https://v3.football.api-sports.io"

def get_match_analysis():
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        return "Football API key is not configured."

    try:
        response = requests.get(
            f"{API_URL}/fixtures",
            headers={"x-apisports-key": key},
            params={"live": "all"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("errors"):
            return "Match data is temporarily unavailable."

        matches = data.get("response", [])
        if not matches:
            return "No live matches available for analysis right now."

        lines = ["📊 LIVE MATCH INTELLIGENCE\n"]

        for match in matches[:5]:
            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            goals = match["goals"]
            league = match["league"]["name"]
            minute = match["fixture"]["status"].get("elapsed")

            lines.append(
                f"⚽ {home} {goals['home']}-{goals['away']} {away}\n"
                f"🏆 {league} | {minute or 0}'"
            )

        return "\n\n".join(lines)

    except (requests.RequestException, ValueError, KeyError, TypeError):
        return "Unable to retrieve match analysis right now."
