"""Create an iCalendar file from the True North Hockey team schedule."""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_ENDPOINT = (
    "https://www.truenorthhockey.com/Schedule/GetTeamScheduleGrid?divteamID=1301"
)
DEFAULT_OUTPUT = "swailers_schedule.ics"
DEFAULT_TIME_ZONE = "America/Toronto"


def fetch(url):
    headers = {"User-Agent": "Mozilla/5.0 (schedule calendar generator)"}
    headers["X-Requested-With"] = "XMLHttpRequest"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def month_number(month_text):
    return datetime.strptime(month_text, "%b").month


def season_start_year(schedule_dates):
    today = date.today()
    earliest_month = min(
        month_number(item["gameDate"].strip().split()[0])
        for item in schedule_dates
    )
    return today.year - (1 if earliest_month > today.month else 0)


def parse_game_datetime(game, start_year):
    month_name, day_text = game["gameDate"].strip().split()
    month = month_number(month_name)
    day = int(day_text)
    year = start_year + (1 if month < 7 else 0)
    game_time = datetime.strptime(game["gameTime"].strip(), "%H:%M").time()
    return datetime(year, month, day, game_time.hour, game_time.minute)


def ics_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def fold_ics_line(line, limit=75):
    """Fold an iCalendar line at UTF-8 byte boundaries."""
    chunks = []
    current = ""
    current_bytes = 0
    for character in line:
        character_bytes = len(character.encode("utf-8"))
        if current and current_bytes + character_bytes > limit:
            chunks.append(current)
            current = " " + character
            current_bytes = 1 + character_bytes
        else:
            current += character
            current_bytes += character_bytes
    if current:
        chunks.append(current)
    return "\r\n".join(chunks)


def create_calendar(games, output_path, source_url, time_zone):
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//smorrell//True North Hockey Schedule//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape('Swailers Schedule')}",
        f"X-WR-TIMEZONE:{ics_escape(time_zone)}",
    ]

    for game in sorted(games, key=lambda item: item["start"]):
        start = game["start"]
        end = start + timedelta(hours=1)
        home = game["homeTeamName"].strip()
        away = game["awayTeamName"].strip()
        title = f"{away} at {home}"
        location = game["rinkName"].strip()
        description = f"{away} at {home}\\nSource: {source_url}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:truenorth-{game['id']}@smorrell",
                f"DTSTAMP:{generated_at}",
                f"DTSTART;TZID={time_zone}:{start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={time_zone}:{end.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{ics_escape(title)}",
                f"LOCATION:{ics_escape(location)}",
                f"DESCRIPTION:{ics_escape(description)}",
                f"URL:{source_url}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    output_path.write_text(
        "\r\n".join(fold_ics_line(line) for line in lines) + "\r\n",
        encoding="utf-8",
        newline="",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_ENDPOINT, help="Schedule JSON endpoint")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output .ics path")
    parser.add_argument("--time-zone", default=DEFAULT_TIME_ZONE, help="TZID for game times")
    args = parser.parse_args()

    payload = json.loads(fetch(args.url))
    games = payload.get("dt", {}).get("it", [])
    if not games:
        raise ValueError("The schedule endpoint returned no games.")

    start_year = season_start_year(games)
    for game in games:
        game["start"] = parse_game_datetime(game, start_year)

    output_path = Path(args.output)
    create_calendar(games, output_path, args.url, args.time_zone)
    print(f"Wrote {len(games)} game(s) to {output_path}.")


if __name__ == "__main__":
    main()
