import os
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import formatdate
import sys

try:
    from git import Repo
    import yt_dlp
except ImportError:
    print("Required packages are missing. Please run installation.bat first.")
    sys.exit(1)

# --- CONFIGURATION ---
RUMBLE_CHANNEL_URL = "https://rumble.com/c/AnnCoulter"
REPO_PATH = r".\your-local-github-repo"  # Adjust this to your local cloned repo path
AUDIO_DIR = os.path.join(REPO_PATH, "mp3s")
RSS_FEED_PATH = os.path.join(REPO_PATH, "feed.xml")
BASE_URL = "https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/"

# Podcast Meta
PODCAST_TITLE = "My Rumble Podcast"
PODCAST_LINK = "https://rumble.com/"
PODCAST_DESC = "Audio mirrors of my favorite Rumble channel."

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
        "outtmpl": os.path.join(AUDIO_DIR, "%(id)s.%(ext)s"),
        "download_archive": os.path.join(REPO_PATH, "downloaded_videos.txt"),
    }

    print("Checking Rumble for new videos...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(RUMBLE_CHANNEL_URL, download=True)
            return info.get("entries", []) if "entries" in info else [info]
        except Exception as e:
            print(f"Error fetching channel: {e}")
            return []

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

    for file_name in os.listdir(AUDIO_DIR):
        if not file_name.endswith(".mp3"):
            continue

        video_id = os.path.splitext(file_name)[0]
        file_path = os.path.join(AUDIO_DIR, file_name)
        file_size = os.path.getsize(file_path)

        entry_meta = next(
            (item for item in downloaded_entries if item and item.get("id") == video_id),
            None,
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

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = description
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "guid", isPermaLink="false").text = video_id

        ET.SubElement(
            item, "enclosure", url=audio_url, length=str(file_size), type="audio/mpeg"
        )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ", level=0)
    tree.write(RSS_FEED_PATH, encoding="utf-8", xml_declaration=True)

def push_to_github():
    """Commits and pushes the new files to the remote GitHub repository."""
    print("Pushing updates to GitHub...")
    try:
        repo = Repo(REPO_PATH)
        repo.git.add(A=True)

        if repo.is_dirty(index=True):
            repo.index.commit(
                f"Automated Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            origin = repo.remote(name="origin")
            origin.push()
            print("Successfully pushed to GitHub!")
        else:
            print("No new changes to commit.")
    except Exception as e:
        print(f"Git operation failed: {e}")

if __name__ == "__main__":
    entries = download_and_convert()
    update_rss_feed(entries)
    push_to_github()
