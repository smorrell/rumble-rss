import os
import re
import json
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import formatdate
import importlib.util
import sys
from urllib.parse import urljoin
from urllib.request import Request, urlopen

try:
    import yt_dlp
    from yt_dlp.networking.impersonate import ImpersonateTarget
except ImportError:
    print("Required packages are missing. Please run installation.bat first.")
    sys.exit(1)

curl_cffi = importlib.util.find_spec("curl_cffi")

# --- CONFIGURATION ---
RUMBLE_CHANNEL_URLS = [
    "https://rumble.com/c/AnnCoulter",
    "https://rumble.com/c/nickjfuentes"
]
MAX_VIDEO_AGE_DAYS = 7
MAX_DOWNLOADS_PER_RUN = 1
REPO_PATH = r"."  # Adjust this to your local cloned repo path
AUDIO_DIR = os.path.join(REPO_PATH, "mp3s")
RSS_FEED_PATH = os.path.join(REPO_PATH, "feed.xml")
METADATA_PATH = os.path.join(AUDIO_DIR, "video_metadata.json")
BASE_URL = "http://10.0.0.182:3000/"

# Podcast Meta
PODCAST_TITLE = "My Rumble Podcast"
PODCAST_LINK = "https://rumble.com/"
PODCAST_DESC = "Audio mirrors of my favorite Rumble channel."


def discover_channel_videos(channel_url):
    """Find video URLs from Rumble's current channel page markup."""
    video_pattern = re.compile(
        r"(?:https://rumble\.com)?(/v(?!ideos)[\w.-]+\.html)", re.IGNORECASE
    )
    video_urls = []

    for page_number in range(1, 2):
        page_url = f"{channel_url}?page={page_number}"
        try:
            request = Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=30) as response:
                webpage = response.read().decode("utf-8", errors="replace")
        except Exception as error:
            if page_number > 1 and getattr(error, "code", None) == 404:
                break
            print(f"Error reading channel page {page_number}: {error}")
            break

        page_urls = list(
            dict.fromkeys(
                urljoin("https://rumble.com", path)
                for path in video_pattern.findall(webpage)
            )
        )
        new_urls = [video_url for video_url in page_urls if video_url not in video_urls]
        video_urls.extend(new_urls)
        print(f"Found {len(new_urls)} videos on channel page {page_number}.")

        if page_number > 1 and not new_urls:
            break

    return video_urls

def download_and_convert():
    """Downloads new videos from Rumble, converts to MP3, and returns metadata."""
    os.makedirs(AUDIO_DIR, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "outtmpl": os.path.join(
            AUDIO_DIR, "%(upload_date>%Y-%m-%d)s - %(title)s.%(ext)s"
        ),
        "download_archive": os.path.join(AUDIO_DIR, "downloaded_videos.txt"),
        "dateafter": f"now-{MAX_VIDEO_AGE_DAYS}days",
        "http_headers": {
            "Referer": "https://rumble.com/",
            "Origin": "https://rumble.com",
        },
    }
    if curl_cffi:
        ydl_opts["impersonate"] = ImpersonateTarget(client="firefox")
    else:
        print(
            "Warning: curl-cffi is not installed; Rumble may reject requests with HTTP 403. "
            "Run installation.bat to install it."
        )

    print("Checking Rumble for new videos...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        entries = []
        for channel_url in RUMBLE_CHANNEL_URLS:
            video_urls = discover_channel_videos(channel_url)
            for video_url in video_urls[:MAX_DOWNLOADS_PER_RUN]:
                try:
                    info = ydl.extract_info(video_url, download=True)
                    if info:
                        entries.append(info)
                except Exception as error:
                    print(f"Error fetching video {video_url}: {error}")

        metadata = {}
        if os.path.exists(METADATA_PATH):
            with open(METADATA_PATH, encoding="utf-8") as metadata_file:
                metadata = json.load(metadata_file)

        for entry in entries:
            if entry and entry.get("id"):
                prepared_name = os.path.basename(ydl.prepare_filename(entry))
                output_name = f"{os.path.splitext(prepared_name)[0]}.mp3"
                metadata[entry["id"]] = {
                    "title": entry.get("title"),
                    "description": entry.get("description"),
                    "upload_date": entry.get("upload_date"),
                    "filename": output_name,
                }

        with open(METADATA_PATH, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)

        return entries

def update_rss_feed(downloaded_entries):
    """Generates or updates the RSS feed XML file."""
    print("Updating RSS feed...")

    rss = ET.Element(
        "rss", version="2.0", xmlns_itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
    )
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "link").text = PODCAST_LINK
    ET.SubElement(channel, "description").text = PODCAST_DESC

    if not os.path.exists(AUDIO_DIR):
        return

    metadata = {}
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH, encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)

    for file_name in os.listdir(AUDIO_DIR):
        if not file_name.endswith(".mp3"):
            continue

        file_path = os.path.join(AUDIO_DIR, file_name)
        file_size = os.path.getsize(file_path)

        entry_meta = next(
            (item for item in metadata.values() if item.get("filename") == file_name),
            None,
        )

        video_id = next(
            (
                video_id
                for video_id, item in metadata.items()
                if item.get("filename") == file_name
            ),
            os.path.splitext(file_name)[0],
        )

        title = (
            entry_meta.get("title", f"Episode {video_id}")
            if entry_meta
            else f"Episode {video_id}"
        )
        description = (
            entry_meta.get("description", "No description available.")
            if entry_meta
            else ""
        )

        if entry_meta and entry_meta.get("upload_date"):
            try:
                date_obj = datetime.strptime(entry_meta["upload_date"], "%Y%m%d")
                pub_date = formatdate(float(date_obj.timestamp()))
            except ValueError:
                pub_date = formatdate()
        else:
            pub_date = formatdate()

        audio_url = f"{BASE_URL}mp3s/{file_name}"
        file_guid = hashlib.sha256(file_name.encode("utf-8")).hexdigest()

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = description
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "guid", isPermaLink="false").text = file_guid

        ET.SubElement(
            item, "enclosure", url=audio_url, length=str(file_size), type="audio/mpeg"
        )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ", level=0)
    tree.write(RSS_FEED_PATH, encoding="utf-8", xml_declaration=True)

if __name__ == "__main__":
    entries = download_and_convert()
    update_rss_feed(entries)
