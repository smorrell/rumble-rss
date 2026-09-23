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
EPISODE_OFFSET_YEARS = 4
EPISODE_WINDOW_MONTHS = 1
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"


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


def normalize_title(title):
    if not title:
        return title
    if title.lower().startswith("classic "):
        return title
    return f"Classic {title}"


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
    channel_description = channel.find("description")
    if channel_description is not None:
        channel.remove(channel_description)
    channel_summary = channel.find(f"{{{ITUNES_NAMESPACE}}}summary")
    if channel_summary is not None:
        channel.remove(channel_summary)

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
        title = item.find("title")
        if title is not None and title.text:
            title.text = normalize_title(title.text)
        item_description = item.find("description")
        if item_description is not None:
            item.remove(item_description)
        item_summary = item.find(f"{{{ITUNES_NAMESPACE}}}summary")
        if item_summary is not None:
            item.remove(item_summary)
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
