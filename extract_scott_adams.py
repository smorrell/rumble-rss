from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
import calendar
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


FEED_URL = "https://anchor.fm/s/128d072c/podcast/rss"
OUTPUT_PATH = Path(__file__).with_name("ScottAdams.xml")
MAX_EPISODES = 10
FEED_TITLE = "Classic Real Coffee with Scott Adams"
EPISODE_OFFSET_YEARS = 3
EPISODE_WINDOW_MONTHS = 1


def subtract_years(value, years):
    """Subtract calendar years while handling February 29."""
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def add_years(value, years):
    """Add calendar years while handling February 29."""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def subtract_months(value, months):
    """Subtract calendar months while handling shorter target months."""
    month_index = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(month_index, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def episode_date(item):
    pub_date = item.findtext("pubDate")
    if not pub_date:
        return None

    try:
        return parsedate_to_datetime(pub_date).date()
    except (TypeError, ValueError):
        return None


def main():
    today = date.today()
    newest_date = subtract_years(today, EPISODE_OFFSET_YEARS)
    oldest_date = subtract_months(newest_date, EPISODE_WINDOW_MONTHS)

    request = Request(
        FEED_URL,
        headers={"User-Agent": "Mozilla/5.0 (RSS episode extractor)"},
    )
    with urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())

    channel = root.find("channel")
    if channel is None:
        raise ValueError("The downloaded feed does not contain an RSS channel.")
    channel.find("title").text = FEED_TITLE

    selected_items = []
    for item in channel.findall("item"):
        published = episode_date(item)
        if published is not None and oldest_date <= published <= newest_date:
            selected_items.append((published, item))

    selected_items = [
        (published, item)
        for published, item in sorted(
            selected_items, key=lambda entry: entry[0], reverse=True
        )[:MAX_EPISODES]
    ]

    for item in channel.findall("item"):
        channel.remove(item)
    for published, item in selected_items:
        item.find("pubDate").text = add_years(
            published, EPISODE_OFFSET_YEARS
        ).strftime("%a, %d %b %Y 00:00:00 GMT")
        channel.append(item)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(OUTPUT_PATH, encoding="utf-8", xml_declaration=True)

    print(
        f"Wrote {len(selected_items)} episode(s) to {OUTPUT_PATH} "
        f"for {oldest_date} through {newest_date}."
    )


if __name__ == "__main__":
    main()
