from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


FEED_URL = "https://anchor.fm/s/128d072c/podcast/rss"
OUTPUT_PATH = Path(__file__).with_name("ScottAdams.xml")


def subtract_years(value, years):
    """Subtract calendar years while handling February 29."""
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


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
    newest_date = subtract_years(today, 2)
    oldest_date = subtract_years(today, 3)

    request = Request(
        FEED_URL,
        headers={"User-Agent": "Mozilla/5.0 (RSS episode extractor)"},
    )
    with urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())

    channel = root.find("channel")
    if channel is None:
        raise ValueError("The downloaded feed does not contain an RSS channel.")

    selected_items = []
    for item in channel.findall("item"):
        published = episode_date(item)
        if published is not None and oldest_date <= published <= newest_date:
            selected_items.append(item)

    for item in channel.findall("item"):
        channel.remove(item)
    for item in selected_items:
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
