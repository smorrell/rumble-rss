import os
import re
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import importlib.util
import sys
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

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
MAX_VIDEO_AGE_DAYS = 5
MAX_DOWNLOADS_PER_RUN = 7   
REPO_PATH = r"."  # Adjust this to your local cloned repo path
AUDIO_DIR = os.path.join(REPO_PATH, "mp3s")
METADATA_PATH = os.path.join(AUDIO_DIR, "video_metadata.json")
ANN_COULTER_FEED_PATH = os.path.join(REPO_PATH, "AnnCoulter.xml")
ANN_COULTER_CHANNEL_URL = "https://rumble.com/c/AnnCoulter"
PODCAST_COVER_URL = (
    "https://raw.githubusercontent.com/smorrell/rumble-rss/master/podcast_cover.jpg"
)
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NAMESPACE)


def sanitize_mp3_filename(filename):
    """Replace non-ASCII-alphanumeric characters in an MP3 basename with hyphens."""
    basename = os.path.splitext(os.path.basename(filename))[0]
    sanitized_basename = re.sub(r"[^A-Za-z0-9]", "-", basename)
    return f"{sanitized_basename}.mp3"


def remove_expired_downloads(metadata):
    """Remove MP3s and metadata entries for videos older than the retention period."""
    cutoff_date = datetime.now().date() - timedelta(days=MAX_VIDEO_AGE_DAYS)
    expired_ids = []

    for video_id, item in metadata.items():
        upload_date = item.get("upload_date")
        if not upload_date:
            continue

        try:
            video_date = datetime.strptime(upload_date, "%Y%m%d").date()
        except ValueError:
            print(f"Skipping cleanup for {video_id}: invalid upload date {upload_date}.")
            continue

        if video_date < cutoff_date:
            filename = item.get("filename")
            if filename:
                file_path = os.path.join(AUDIO_DIR, os.path.basename(filename))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Removed expired MP3: {filename}")
            expired_ids.append(video_id)

    for video_id in expired_ids:
        del metadata[video_id]

    if expired_ids:
        with open(METADATA_PATH, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)
        entry_label = "entry" if len(expired_ids) == 1 else "entries"
        print(f"Removed {len(expired_ids)} expired video metadata {entry_label}.")


def is_recent_video(info):
    """Return whether yt-dlp metadata contains a video within the retention window."""
    upload_date = info.get("upload_date") if info else None
    if not upload_date:
        return False

    try:
        video_date = datetime.strptime(upload_date, "%Y%m%d").date()
    except ValueError:
        return False

    cutoff_date = datetime.now().date() - timedelta(days=MAX_VIDEO_AGE_DAYS)
    return video_date >= cutoff_date


def write_ann_coulter_feed(metadata):
    """Write an RSS feed containing downloaded Ann Coulter episodes."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Ann and Nick"
    ET.SubElement(channel, "link").text = ANN_COULTER_CHANNEL_URL
    ET.SubElement(channel, "description").text = "Downloaded Ann Coulter episodes."
    ET.SubElement(
        channel,
        f"{{{ITUNES_NAMESPACE}}}image",
        href=PODCAST_COVER_URL,
    )
    items_container = channel
    items = []
    ann_entries = [
        (video_id, item)
        for video_id, item in metadata.items()
        if item.get("channel_url") == ANN_COULTER_CHANNEL_URL
    ]
    ann_entries.sort(key=lambda entry: entry[1].get("upload_date") or "", reverse=True)

    for video_id, item in ann_entries:
        upload_date = item.get("upload_date")
        try:
            published = datetime.strptime(upload_date, "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            continue

        rss_item = ET.SubElement(items_container, "item")
        ET.SubElement(rss_item, "title").text = item.get("title") or f"Episode {video_id}"
        ET.SubElement(rss_item, "description").text = item.get("description") or ""
        ET.SubElement(rss_item, "pubDate").text = format_datetime(published, usegmt=True)
        ET.SubElement(rss_item, "guid", isPermaLink="false").text = video_id
        filename = item.get("filename")
        if filename:
            ET.SubElement(
                rss_item,
                "enclosure",
                url=f"/mp3s/{quote(os.path.basename(filename))}",
                type="audio/mpeg",
            )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(ANN_COULTER_FEED_PATH, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {len(ann_entries)} Ann Coulter episode(s) to {ANN_COULTER_FEED_PATH}.")


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
                "preferredquality": "16",
            }
        ],
        "outtmpl": os.path.join(
            AUDIO_DIR, "%(upload_date>%Y-%m-%d)s - %(title)s.%(ext)s"
        ),
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
        metadata = {}
        if os.path.exists(METADATA_PATH):
            with open(METADATA_PATH, encoding="utf-8") as metadata_file:
                metadata = json.load(metadata_file)
        remove_expired_downloads(metadata)

        for channel_url in RUMBLE_CHANNEL_URLS:
            video_urls = discover_channel_videos(channel_url)
            channel_downloads = 0
            for video_url in video_urls:
                if channel_downloads >= MAX_DOWNLOADS_PER_RUN:
                    break
                try:
                    print(f"Video URL: {video_url}")
                    info = ydl.extract_info(video_url, download=False)
                    if info and info.get("id") in metadata:
                        if metadata[info["id"]].get("channel_url") != channel_url:
                            metadata[info["id"]]["channel_url"] = channel_url
                            with open(METADATA_PATH, "w", encoding="utf-8") as metadata_file:
                                json.dump(
                                    metadata,
                                    metadata_file,
                                    ensure_ascii=False,
                                    indent=2,
                                )
                        print(f"Skipping already downloaded video {video_url}.")
                        continue

                    if not is_recent_video(info):
                        upload_date = info.get("upload_date") if info else None
                        print(
                            f"Skipping old or undated video {video_url} "
                            f"(upload_date: {upload_date or 'unknown'})."
                        )
                        continue

                    duration = info.get("duration") if info else None
                    if duration is None or duration >= (3600 * 1.5):
                        print(f"Skipping video {video_url}: duration is not less than 1 hour.")
                        continue

                    info = ydl.extract_info(video_url, download=True)
                    if info:
                        entries.append(info)
                        channel_downloads += 1
                        if info.get("id"):
                            prepared_name = os.path.basename(ydl.prepare_filename(info))
                            source_name = f"{os.path.splitext(prepared_name)[0]}.mp3"
                            output_name = sanitize_mp3_filename(source_name)
                            if source_name != output_name:
                                source_path = os.path.join(AUDIO_DIR, source_name)
                                output_path = os.path.join(AUDIO_DIR, output_name)
                                if os.path.exists(output_path):
                                    output_name = sanitize_mp3_filename(
                                        f"{os.path.splitext(source_name)[0]}-{info['id']}.mp3"
                                    )
                                    output_path = os.path.join(AUDIO_DIR, output_name)
                                os.rename(source_path, output_path)
                            metadata[info["id"]] = {
                                "title": info.get("title"),
                                "description": info.get("description"),
                                "upload_date": info.get("upload_date"),
                                "filename": output_name,
                                "channel_url": channel_url,
                            }
                            with open(
                                METADATA_PATH, "w", encoding="utf-8"
                            ) as metadata_file:
                                json.dump(
                                    metadata,
                                    metadata_file,
                                    ensure_ascii=False,
                                    indent=2,
                                )
                except Exception as error:
                    print(f"Error fetching video {video_url}: {error}")

        write_ann_coulter_feed(metadata)
        return entries

if __name__ == "__main__":
    download_and_convert()
