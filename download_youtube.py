"""Download a YouTube video with yt-dlp."""

import argparse
from pathlib import Path

import yt_dlp

DEFAULT_URL = "https://www.youtube.com/watch?v=ds8ArbgeblM"
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("downloads")


def download_video(url, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "outtmpl": str(output_dir / "%(title)s [%(id)s].%(ext)s"),
        "postprocessor_args": {
            "Merger": ["-c:a", "aac", "-b:a", "192k"],
        },
    }

    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.download([url])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="YouTube video URL")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the downloaded video will be saved",
    )
    args = parser.parse_args()
    download_video(args.url, args.output_dir)


if __name__ == "__main__":
    main()
