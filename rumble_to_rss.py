import os
import re
import json
import shutil
import tempfile
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
import importlib.util
import sys
from io import BytesIO
from script_logging import configure_script_logging
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

if __name__ == "__main__":
    configure_script_logging("rumble_to_rss.txt")

try:
    import yt_dlp
    from yt_dlp.networking.impersonate import ImpersonateTarget
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:
    print(
        "Required packages are missing. Please run installation.bat first "
        "to install yt-dlp and Pillow."
    )
    sys.exit(1)

curl_cffi = importlib.util.find_spec("curl_cffi")

# --- CONFIGURATION ---
REPO_PATH = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class ChannelConfig:
    """Channel settings; max_duration_minutes is in minutes."""

    url: str
    prefix: str
    image_label: str
    max_duration_minutes: int
    paused: bool = False


CHANNEL_CONFIG_PATH = os.path.join(REPO_PATH, "channels.json")
with open(CHANNEL_CONFIG_PATH, encoding="utf-8") as channel_config_file:
    CHANNELS = [
        ChannelConfig(**channel_data)
        for channel_data in json.load(channel_config_file)
    ]
YOUTUBE_MAX_VIDEOS = 5
MAX_VIDEO_AGE_DAYS = 7
MAX_DOWNLOADS_PER_RUN = 25
FILTER_RETRY_HOURS = 24
AUDIO_DIR = os.path.join(REPO_PATH, "mp3s")
IMAGE_DIR = os.path.join(REPO_PATH, "img")
THUMBNAIL_CACHE_PATH = os.path.join(IMAGE_DIR, "thumbnail_sources.json")
METADATA_PATH = os.path.join(AUDIO_DIR, "video_metadata.json")
FILTERED_VIDEOS_PATH = os.path.join(AUDIO_DIR, "filtered_video_urls.json")
RSS_FEED_PATH = os.path.join(REPO_PATH, "Rumble.xml")
AZURE_STORAGE_ACCOUNT_NAME = os.environ.get(
    "AZURE_STORAGE_ACCOUNT_NAME", "podcasttrimmeraf20240207"
)
AZURE_STORAGE_CONTAINER_NAME = os.environ.get(
    "AZURE_STORAGE_CONTAINER_NAME", "podcastmp3s"
)
AZURE_CONTAINER_URL = (
    f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/"
    f"{AZURE_STORAGE_CONTAINER_NAME}"
)
FEED_BASE_URL = os.environ.get("FEED_BASE_URL", AZURE_CONTAINER_URL).rstrip("/")
PODCAST_COVER_URL = f"{FEED_BASE_URL}/img/podcast_cover.jpg"
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NAMESPACE)


class EpisodeThumbnailParser(HTMLParser):
    """Find the first episode thumbnail with a platform-specific image class."""

    def __init__(self, image_class):
        super().__init__()
        self.image_class = image_class
        self.image_url = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if (
            self.image_url is None
            and tag == "img"
            and self.image_class in (attributes.get("class") or "").split()
        ):
            self.image_url = (
                attributes.get("src")
                or attributes.get("data-src")
                or attributes.get("data-thumb")
            )
            if not self.image_url and attributes.get("srcset"):
                self.image_url = attributes["srcset"].split(",")[-1].strip().split()[0]


def channel_episode_thumbnail_url(channel_url):
    """Return the latest episode thumbnail URL for a configured channel."""
    image_class = (
        "ytCoreImageHost"
        if "youtube.com/" in channel_url
        else "rum-video-thumbnail__image"
    )
    page_error = None

    try:
        request = Request(channel_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as response:
            webpage = response.read().decode("utf-8", errors="replace")
        parser = EpisodeThumbnailParser(image_class)
        parser.feed(webpage)
        if parser.image_url:
            return urljoin(channel_url, parser.image_url)
    except OSError as error:
        page_error = error

    options = {
        "extract_flat": "in_playlist",
        "playlistend": 1,
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "http_headers": {
            "Referer": "https://rumble.com/",
            "Origin": "https://rumble.com",
        },
    }
    if curl_cffi:
        options["impersonate"] = ImpersonateTarget(client="chrome")
    if shutil.which("node"):
        options["js_runtimes"] = {"node": {}}

    with yt_dlp.YoutubeDL(options) as ydl:
        video_urls = discover_channel_videos(channel_url, ydl)
        if not video_urls:
            detail = f" Page request failed: {page_error}" if page_error else ""
            raise RuntimeError(
                f"No latest episode found for {channel_url}.{detail}"
            )
        episode_info = ydl.extract_info(video_urls[0], download=False)

    if not episode_info:
        raise RuntimeError(f"Could not read the latest episode for {channel_url}.")
    thumbnail_url = episode_info.get("thumbnail")
    if not thumbnail_url:
        thumbnails = [
            thumbnail
            for thumbnail in (episode_info.get("thumbnails") or [])
            if thumbnail.get("url")
        ]
        if thumbnails:
            thumbnail_url = thumbnails[-1]["url"]
    if not thumbnail_url:
        raise RuntimeError(
            f"No latest episode thumbnail found for {channel_url}."
        )
    return thumbnail_url


def download_channel_images():
    """Refresh channel portraits and build the square podcast-cover collage."""
    print("Refreshing channel portraits and podcast cover...")
    os.makedirs(IMAGE_DIR, exist_ok=True)
    portraits = []
    portrait_temporary_paths = []
    temporary_paths = []
    active_channels = [channel for channel in CHANNELS if not channel.paused]
    if not active_channels:
        print("No active channels; keeping the existing podcast cover.")
        return
    cover_path = os.path.join(IMAGE_DIR, "podcast_cover.jpg")

    def image_is_fresh(path):
        try:
            return datetime.now().timestamp() - os.path.getmtime(path) < 24 * 60 * 60
        except FileNotFoundError:
            return False

    try:
        with open(THUMBNAIL_CACHE_PATH, encoding="utf-8") as cache_file:
            thumbnail_sources = json.load(cache_file)
    except FileNotFoundError:
        thumbnail_sources = {}
    if not isinstance(thumbnail_sources, dict):
        raise ValueError(f"Invalid thumbnail cache: {THUMBNAIL_CACHE_PATH}")

    active_channel_urls = [channel.url for channel in active_channels]
    if (
        thumbnail_sources.get("_active_channels") == active_channel_urls
        and image_is_fresh(cover_path)
        and all(
        image_is_fresh(
            os.path.join(IMAGE_DIR, f"{channel_show_name(channel.url)}.jpg")
        )
        for channel in active_channels
        )
    ):
        print("Channel images and podcast cover are less than 24 hours old.")
        return

    try:
        for channel in active_channels:
            show_name = channel_show_name(channel.url)
            portrait_path = os.path.join(IMAGE_DIR, f"{show_name}.jpg")
            needs_write = False
            if image_is_fresh(portrait_path):
                with Image.open(portrait_path) as source:
                    portrait = source.convert("RGB")
                print(f"Using recent channel image for {show_name}.")
            else:
                thumbnail_url = channel_episode_thumbnail_url(channel.url)
                if (
                    thumbnail_sources.get(channel.url) == thumbnail_url
                    and os.path.isfile(portrait_path)
                ):
                    with Image.open(portrait_path) as source:
                        portrait = source.convert("RGB")
                    print(f"Using cached latest episode thumbnail for {show_name}.")
                else:
                    request = Request(
                        thumbnail_url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urlopen(request, timeout=30) as response:
                        thumbnail_data = response.read()

                    with Image.open(BytesIO(thumbnail_data)) as source:
                        thumbnail = ImageOps.contain(
                            source.convert("RGB"),
                            (540, 468),
                            method=Image.Resampling.LANCZOS,
                        )
                    portrait = Image.new("RGB", (540, 540), "#172126")
                    portrait.paste(
                        thumbnail,
                        (
                            (540 - thumbnail.width) // 2,
                            (468 - thumbnail.height) // 2,
                        ),
                    )
                    thumbnail.close()
                    thumbnail_sources[channel.url] = thumbnail_url
                    needs_write = True
                    print(f"Downloaded the latest episode thumbnail for {show_name}.")
            portraits.append(
                (show_name, channel.image_label, portrait, needs_write)
            )

        cover = Image.new("RGB", (1800, 1800), "#263238")
        draw = ImageDraw.Draw(cover)
        try:
            title_font = ImageFont.truetype("arial.ttf", 76)
            label_font = ImageFont.truetype("arial.ttf", 32)
            subtitle_font = ImageFont.truetype("arial.ttf", 30)
        except OSError:
            title_font = ImageFont.load_default()
            label_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()

        title = "LATEST EPISODES"
        title_bounds = draw.textbbox((0, 0), title, font=title_font)
        draw.text(
            ((1800 - (title_bounds[2] - title_bounds[0])) / 2, 82),
            title,
            fill="#FFF4DC",
            font=title_font,
        )
        subtitle = f"{len(portraits)} CHANNELS  |  ONE SHOW"
        subtitle_bounds = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        draw.text(
            ((1800 - (subtitle_bounds[2] - subtitle_bounds[0])) / 2, 190),
            subtitle,
            fill="#E5B66A",
            font=subtitle_font,
        )

        positions = (
            (60, 300),
            (630, 300),
            (1200, 300),
            (60, 870),
            (630, 870),
            (1200, 870),
        )
        panel_colors = (
            "#B64A3A",
            "#476D9A",
            "#628052",
            "#9A6D9A",
            "#CF7C42",
            "#497C78",
        )
        for index, ((_, label, portrait, _), (x, y)) in enumerate(
            zip(portraits, positions)
        ):
            panel_color = panel_colors[index]
            draw.rectangle((x - 8, y - 8, x + 548, y + 548), fill=panel_color)
            cover.paste(portrait, (x, y))
            draw.rectangle((x, y + 468, x + 540, y + 540), fill="#172126")
            label_bounds = draw.textbbox((0, 0), label, font=label_font)
            draw.text(
                (
                    x + (540 - (label_bounds[2] - label_bounds[0])) / 2,
                    y + 486,
                ),
                label,
                fill="#FFFFFF",
                font=label_font,
            )

        footer = "YOUTUBE  +  RUMBLE"
        footer_bounds = draw.textbbox((0, 0), footer, font=subtitle_font)
        draw.text(
            ((1800 - (footer_bounds[2] - footer_bounds[0])) / 2, 1600),
            footer,
            fill="#E5B66A",
            font=subtitle_font,
        )

        for show_name, _, portrait, needs_write in portraits:
            if not needs_write:
                continue
            with tempfile.NamedTemporaryFile(
                dir=IMAGE_DIR, suffix=".jpg", delete=False
            ) as temporary_file:
                temporary_paths.append(temporary_file.name)
                portrait_temporary_paths.append(
                    (show_name, temporary_file.name)
                )
            portrait.save(temporary_paths[-1], format="JPEG", quality=92)

        with tempfile.NamedTemporaryFile(
            dir=IMAGE_DIR, suffix=".jpg", delete=False
        ) as temporary_file:
            temporary_paths.append(temporary_file.name)
            cover_temporary_path = temporary_file.name
        cover.save(cover_temporary_path, format="JPEG", quality=92)

        for show_name, temporary_path in portrait_temporary_paths:
            os.replace(
                temporary_path,
                os.path.join(IMAGE_DIR, f"{show_name}.jpg"),
            )
        os.replace(cover_temporary_path, cover_path)
        thumbnail_sources["_active_channels"] = active_channel_urls
        with tempfile.NamedTemporaryFile(
            dir=IMAGE_DIR, suffix=".json", mode="w", encoding="utf-8", delete=False
        ) as temporary_file:
            temporary_paths.append(temporary_file.name)
            json.dump(thumbnail_sources, temporary_file, ensure_ascii=False, indent=2)
        os.replace(temporary_paths[-1], THUMBNAIL_CACHE_PATH)
        print(f"Updated podcast cover: {cover_path}")
    finally:
        for temporary_path in temporary_paths:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        for _, _, portrait, _ in portraits:
            portrait.close()
        if "cover" in locals():
            cover.close()


def sanitize_mp3_filename(filename):
    """Replace non-ASCII-alphanumeric characters in an MP3 basename with single hyphens."""
    basename = os.path.splitext(os.path.basename(filename))[0]
    sanitized_basename = re.sub(r"[^A-Za-z0-9]", "-", basename)
    sanitized_basename = re.sub(r"-+", "-", sanitized_basename).strip("-")
    return f"{sanitized_basename}.mp3"


def channel_show_name(channel_url):
    """Return a filesystem-safe show name from a channel URL."""
    path_parts = [part for part in channel_url.rstrip("/").split("/") if part]
    show_name = next(
        (part.lstrip("@") for part in reversed(path_parts) if part.lower() != "videos"),
        "channel",
    )
    return re.sub(r"[^A-Za-z0-9]+", "-", show_name).strip("-") or "channel"


def format_episode_title(item, video_id):
    """Prefix an episode title with its channel's configured initials."""
    title = item.get("title") or f"Episode {video_id}"
    channel = next(
        (channel for channel in CHANNELS if channel.url == item.get("channel_url")),
        None,
    )
    prefix = channel.prefix if channel else None
    return f"{prefix} - {title}" if prefix else title


def format_episode_duration(duration):
    """Format seconds as an iTunes-compatible HH:MM:SS duration."""
    try:
        total_seconds = int(duration)
    except (TypeError, ValueError, OverflowError):
        return None
    if total_seconds < 0:
        return None

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


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


def video_filter_reason(info, channel):
    """Return a reason when known video details still fail the current filters."""
    if not isinstance(info, dict):
        return None

    retry_after = info.get("retry_after")
    if retry_after:
        try:
            retry_after = datetime.fromisoformat(retry_after)
        except (TypeError, ValueError):
            retry_after = None
        if retry_after and retry_after.tzinfo is None:
            retry_after = retry_after.replace(tzinfo=timezone.utc)
        if retry_after and datetime.now(timezone.utc) < retry_after:
            return info.get("filter_reason", "previously filtered")

    upload_date = info.get("upload_date") if info else None
    if upload_date:
        try:
            video_date = datetime.strptime(upload_date, "%Y%m%d").date()
        except ValueError:
            video_date = None
        if video_date and video_date < (
            datetime.now().date() - timedelta(days=MAX_VIDEO_AGE_DAYS)
        ):
            return f"older than {MAX_VIDEO_AGE_DAYS} days"

    duration = info.get("duration") if info else None
    if duration is not None and duration >= channel.max_duration_minutes * 60:
        return f"at least {channel.max_duration_minutes} minutes long"
    return None


def write_feed(metadata):
    """Write the generated podcast RSS feed for all enabled channels."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Ann and Nick"
    ET.SubElement(
        channel,
        f"{{{ITUNES_NAMESPACE}}}image",
        href=PODCAST_COVER_URL,
    )
    items_container = channel
    feed_channels = {channel.url for channel in CHANNELS if not channel.paused}
    feed_entries = [
        (metadata_key, item)
        for metadata_key, item in metadata.items()
        if item.get("channel_url") in feed_channels
    ]
    feed_entries.sort(key=lambda entry: entry[1].get("upload_date") or "", reverse=True)

    for metadata_key, item in feed_entries:
        video_id = item.get("video_id") or metadata_key
        upload_date = item.get("upload_date")
        try:
            timestamp = item.get("timestamp")
            if timestamp is not None:
                published = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            else:
                published = datetime.strptime(upload_date, "%Y%m%d").replace(
                    tzinfo=timezone.utc
                )
        except (TypeError, ValueError):
            continue

        rss_item = ET.SubElement(items_container, "item")
        ET.SubElement(rss_item, "title").text = format_episode_title(item, video_id)
        ET.SubElement(rss_item, "pubDate").text = format_datetime(published, usegmt=True)
        ET.SubElement(rss_item, "guid", isPermaLink="false").text = video_id
        duration = format_episode_duration(item.get("duration"))
        if duration:
            ET.SubElement(rss_item, f"{{{ITUNES_NAMESPACE}}}duration").text = duration
        filename = item.get("filename")
        if filename:
            ET.SubElement(
                rss_item,
                "enclosure",
                url=f"{FEED_BASE_URL}/mp3s/{quote(os.path.basename(filename))}",
                type="audio/mpeg",
            )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(RSS_FEED_PATH, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {len(feed_entries)} episode(s) to {RSS_FEED_PATH}.")


def discover_channel_videos(channel_url, ydl):
    """Find video URLs from a Rumble or YouTube channel."""
    if "youtube.com/" in channel_url or "youtu.be/" in channel_url:
        channel_info = ydl.extract_info(channel_url, download=False)
        return [
            entry.get("webpage_url") or entry.get("url")
            for entry in channel_info.get("entries", [])
            if entry and (entry.get("webpage_url") or entry.get("url"))
        ]

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
    """Downloads new videos from Rumble and YouTube, converts to MP3, and returns metadata."""
    download_channel_images()
    os.makedirs(AUDIO_DIR, exist_ok=True)

    def build_ydl_options(channel_url=None):
        show_name = channel_show_name(channel_url) if channel_url else "show"
        opts = {
            "format": "bestaudio/best",
            "playlistend": YOUTUBE_MAX_VIDEOS,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
            "outtmpl": os.path.join(
                AUDIO_DIR,
                f"%(upload_date>%Y-%m-%d)s - {show_name} - %(title)s.%(ext)s",
            ),
            "dateafter": f"now-{MAX_VIDEO_AGE_DAYS}days",
            "http_headers": {
                "Referer": "https://rumble.com/",
                "Origin": "https://rumble.com",
            },
        }
        if shutil.which("node"):
            opts["js_runtimes"] = {"node": {}}
        else:
            print(
                "Warning: Node.js is not installed or not on PATH. yt-dlp needs a JavaScript runtime "
                "for YouTube extraction. Install Node.js or add it to PATH."
            )
        if curl_cffi:
            opts["impersonate"] = ImpersonateTarget(client="chrome")
        else:
            print(
                "Warning: curl-cffi is not installed; Rumble may reject requests with HTTP 403. "
                "Run installation.bat to install it."
            )
        return opts

    metadata = {}
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH, encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
    remove_expired_downloads(metadata)
    filtered_videos = {}
    if os.path.exists(FILTERED_VIDEOS_PATH):
        with open(FILTERED_VIDEOS_PATH, encoding="utf-8") as filtered_file:
            filtered_videos = json.load(filtered_file)
    if not isinstance(filtered_videos, dict):
        raise ValueError(f"Invalid filtered-video cache: {FILTERED_VIDEOS_PATH}")
    metadata_lock = __import__("threading").Lock()

    def save_filtered_videos():
        with open(FILTERED_VIDEOS_PATH, "w", encoding="utf-8") as filtered_file:
            json.dump(filtered_videos, filtered_file, ensure_ascii=False, indent=2)

    def remember_filtered_video(video_url, channel, info, reason, retry=False):
        entry = {
            "upload_date": info.get("upload_date") if info else None,
            "duration": info.get("duration") if info else None,
            "channel_url": channel.url,
        }
        if retry:
            entry["filter_reason"] = reason
            entry["retry_after"] = (
                datetime.now(timezone.utc) + timedelta(hours=FILTER_RETRY_HOURS)
            ).isoformat()
        filtered_videos[video_url] = entry
        save_filtered_videos()

    def fetch_and_convert(video_url, channel, metadata, metadata_lock):
        channel_url = channel.url
        thread_name = f"Thread-{__import__('threading').current_thread().ident}"
        with metadata_lock:
            metadata_entry = metadata.get(video_url)
            filename = metadata_entry.get("filename") if metadata_entry else None
            local_path = (
                os.path.join(AUDIO_DIR, os.path.basename(filename))
                if filename
                else None
            )
            if local_path and os.path.isfile(local_path):
                print(
                    f"[{thread_name}] Skipping already downloaded video {video_url}."
                )
                return None

            cached_reason = video_filter_reason(filtered_videos.get(video_url), channel)
            if cached_reason:
                print(
                    f"[{thread_name}] Skipping previously filtered video "
                    f"{video_url} ({cached_reason})."
                )
                return None
            if video_url in filtered_videos:
                del filtered_videos[video_url]
                save_filtered_videos()

        with yt_dlp.YoutubeDL(build_ydl_options(channel_url)) as ydl:
            try:
                print(f"[{thread_name}] Video URL: {video_url}")
                info = ydl.extract_info(video_url, download=False)
                if not info or not info.get("id"):
                    with metadata_lock:
                        remember_filtered_video(
                            video_url,
                            channel,
                            info,
                            "video metadata unavailable",
                            retry=True,
                        )
                    print(
                        f"[{thread_name}] Skipping video without an ID: {video_url}."
                    )
                    return None
                metadata_key = video_url
                metadata_migrated = False
                with metadata_lock:
                    legacy_entry = metadata.get(info["id"])
                    if (
                        metadata_key not in metadata
                        and legacy_entry
                        and legacy_entry.get("channel_url") == channel_url
                    ):
                        metadata[metadata_key] = metadata.pop(info["id"])
                        metadata_migrated = True
                    if metadata_key in metadata:
                        metadata_entry = metadata[metadata_key]
                        metadata_changed = False
                        if metadata_entry.get("video_url") != metadata_key:
                            metadata_entry["video_url"] = metadata_key
                            metadata_changed = True
                        if metadata_entry.get("video_id") != info["id"]:
                            metadata_entry["video_id"] = info["id"]
                            metadata_changed = True
                        if metadata_entry.get("channel_url") != channel_url:
                            metadata_entry["channel_url"] = channel_url
                            metadata_changed = True
                        duration = info.get("duration")
                        if (
                            duration is not None
                            and metadata_entry.get("duration") != duration
                        ):
                            metadata_entry["duration"] = duration
                            metadata_changed = True
                        filename = metadata_entry.get("filename")
                        local_path = (
                            os.path.join(AUDIO_DIR, os.path.basename(filename))
                            if filename
                            else None
                        )
                        if local_path and os.path.isfile(local_path):
                            if metadata_changed or metadata_migrated:
                                with open(
                                    METADATA_PATH, "w", encoding="utf-8"
                                ) as metadata_file:
                                    json.dump(
                                        metadata,
                                        metadata_file,
                                        ensure_ascii=False,
                                        indent=2,
                                    )
                            print(
                                f"[{thread_name}] Skipping already downloaded video "
                                f"{video_url}."
                            )
                            return None

                    if not is_recent_video(info):
                        upload_date = info.get("upload_date") if info else None
                        filter_reason = video_filter_reason(info, channel)
                        remember_filtered_video(
                            video_url,
                            channel,
                            info,
                            filter_reason or "upload date missing or invalid",
                            retry=filter_reason is None,
                        )
                        print(
                            f"[{thread_name}] Skipping old or undated video {video_url} "
                            f"(upload_date: {upload_date or 'unknown'})."
                        )
                        return None

                    duration = info.get("duration") if info else None
                    if duration is None or duration >= channel.max_duration_minutes * 60:
                        remember_filtered_video(
                            video_url,
                            channel,
                            info,
                            "duration unavailable",
                            retry=duration is None,
                        )
                        print(
                            f"[{thread_name}] Skipping video {video_url}: duration is "
                            f"unknown or not less than the "
                            f"{channel.max_duration_minutes}-minute channel maximum."
                        )
                        return None

                prepared_name = os.path.basename(ydl.prepare_filename(info))
                source_stem = os.path.splitext(prepared_name)[0]
                source_name = f"{source_stem}.mp3"
                output_name = sanitize_mp3_filename(source_name)
                existing_names = [output_name]
                if source_name != output_name:
                    existing_names.append(
                        sanitize_mp3_filename(f"{source_stem}-{info['id']}.mp3")
                    )
                existing_name = next(
                    (
                        name
                        for name in existing_names
                        if os.path.isfile(os.path.join(AUDIO_DIR, name))
                    ),
                    None,
                )
                if existing_name:
                    output_name = existing_name
                    metadata_entry = {
                        "video_id": info["id"],
                        "video_url": metadata_key,
                        "title": info.get("title"),
                        "description": info.get("description"),
                        "upload_date": info.get("upload_date"),
                        "timestamp": info.get("timestamp"),
                        "duration": info.get("duration"),
                        "filename": output_name,
                        "channel_url": channel_url,
                    }
                    with metadata_lock:
                        metadata[metadata_key] = metadata_entry
                        with open(
                            METADATA_PATH, "w", encoding="utf-8"
                        ) as metadata_file:
                            json.dump(
                                metadata,
                                metadata_file,
                                ensure_ascii=False,
                                indent=2,
                            )
                    print(
                        f"[{thread_name}] Skipping existing local file {output_name}."
                    )
                    return None

                info = ydl.extract_info(video_url, download=True)
                if not info or not info.get("id"):
                    return None

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

                metadata_entry = {
                    "video_id": info["id"],
                    "video_url": metadata_key,
                    "title": info.get("title"),
                    "description": info.get("description"),
                    "upload_date": info.get("upload_date"),
                    "timestamp": info.get("timestamp"),
                    "duration": info.get("duration"),
                    "filename": output_name,
                    "channel_url": channel_url,
                }

                with metadata_lock:
                    metadata[metadata_key] = metadata_entry
                    with open(METADATA_PATH, "w", encoding="utf-8") as metadata_file:
                        json.dump(
                            metadata,
                            metadata_file,
                            ensure_ascii=False,
                            indent=2,
                        )
                return info
            except Exception as error:
                print(f"[{thread_name}] Error fetching video {video_url}: {error}")
                return None

    print("Checking Rumble for new videos...")
    entries = []

    pending_tasks = []
    for channel in CHANNELS:
        if channel.paused:
            print(f"Skipping paused channel {channel.url}.")
            continue
        ydl = yt_dlp.YoutubeDL(build_ydl_options())
        try:
            video_urls = discover_channel_videos(channel.url, ydl)
        finally:
            ydl.close()

        channel_downloads = 0
        for video_url in video_urls:
            if channel_downloads >= MAX_DOWNLOADS_PER_RUN:
                break
            pending_tasks.append((video_url, channel))
            channel_downloads += 1

    max_workers = 4
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_and_convert, video_url, channel, metadata, metadata_lock)
            for video_url, channel in pending_tasks
        ]
        for future in as_completed(futures):
            result = future.result()
            if result:
                entries.append(result)

    write_feed(metadata)
    return entries

if __name__ == "__main__":
    download_and_convert()
