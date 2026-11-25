import os
from datetime import datetime, timedelta, timezone

import requests

API_URL = "https://v3.football.api-sports.io"


def get_fixture_data(limit=20):
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        raise RuntimeError("Football API key is not configured")

    now = datetime.now(timezone.utc)
    fixtures = []

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
            raise RuntimeError("Football data temporarily unavailable")

        for match in data.get("response", []):
            fixture = match["fixture"]
            status = fixture["status"]["short"]
            kickoff = datetime.fromisoformat(
                fixture["date"].replace("Z", "+00:00")
            )

            if status in {"1H", "2H", "HT", "ET", "BT", "P", "INT", "LIVE"}:
                category = "live"
            elif status in {"NS", "TBD"} and now <= kickoff < now + timedelta(hours=24):
                category = "upcoming"
            else:
                continue

            fixtures.append({
                "id": fixture["id"],
                "home": match["teams"]["home"]["name"],
                "away": match["teams"]["away"]["name"],
                "league": match["league"]["name"],
                "kickoff": kickoff.isoformat(),
                "status": status,
                "category": category,
                "home_goals": match["goals"]["home"],
                "away_goals": match["goals"]["away"],
            })

    fixtures.sort(
        key=lambda item: (
            item["category"] != "live",
            item["kickoff"],
        )
    )
    return {"fixtures": fixtures[:limit]}
