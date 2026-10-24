import logging
import os
from pathlib import Path

try:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.storage.blob import BlobServiceClient, ContentSettings
except ImportError:
    raise SystemExit(
        "Azure Blob Storage dependencies are missing. "
        "Run installation.bat to install them."
    )


logger = logging.getLogger(__name__)

REPO_PATH = Path(__file__).resolve().parent
MP3_DIR = REPO_PATH / "mp3s"
CONTAINER_NAME = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "podcastmp3s")
ACCOUNT_NAME = os.environ.get(
    "AZURE_STORAGE_ACCOUNT_NAME", "podcasttrimmeraf20240207"
)
FEED_FILES = ("Rumble.xml", "ScottAdams.xml")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting upload to Azure container '%s'.", CONTAINER_NAME)

    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        logger.error("AZURE_STORAGE_CONNECTION_STRING is not set.")
        raise SystemExit(
            "Set the AZURE_STORAGE_CONNECTION_STRING environment variable."
        )

    cover_path = REPO_PATH / "podcast_cover.jpg"
    feed_paths = [REPO_PATH / filename for filename in FEED_FILES]
    required_paths = [cover_path, *feed_paths]
    missing_paths = [path for path in required_paths if not path.is_file()]
    if missing_paths:
        missing = ", ".join(str(path) for path in missing_paths)
        logger.error("Required upload file(s) not found: %s", missing)
        raise SystemExit(f"Required upload file(s) not found: {missing}")

    logger.info("Connecting to Azure Blob Storage.")
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container = blob_service.get_container_client(CONTAINER_NAME)
    try:
        properties = container.get_container_properties()
    except ResourceNotFoundError:
        logger.info("Creating container '%s' with public blob access.", CONTAINER_NAME)
        container.create_container(public_access="blob")
        logger.info("Created container '%s'.", CONTAINER_NAME)
    else:
        if properties.public_access != "blob":
            logger.info("Enabling public blob access on '%s'.", CONTAINER_NAME)
            container.set_container_access_policy(
                signed_identifiers={}, public_access="blob"
            )
            logger.info("Enabled public blob access on '%s'.", CONTAINER_NAME)

    def upload_file(path, blob_name, content_type):
        blob = container.get_blob_client(blob_name)
        logger.info("Uploading '%s'.", blob_name)
        with path.open("rb") as data:
            blob.upload_blob(
                data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
        logger.info("Uploaded '%s'.", blob_name)

    for mp3_path in sorted(MP3_DIR.glob("*.mp3")):
        upload_file(mp3_path, f"mp3s/{mp3_path.name}", "audio/mpeg")

    upload_file(cover_path, cover_path.name, "image/jpeg")
    for feed_path in feed_paths:
        upload_file(feed_path, feed_path.name, "application/rss+xml")

    logger.info(
        "Rumble feed URL: "
        f"https://{ACCOUNT_NAME}.blob.core.windows.net/"
        f"{CONTAINER_NAME}/Rumble.xml"
    )
    logger.info(
        "Scott Adams feed URL: "
        f"https://{ACCOUNT_NAME}.blob.core.windows.net/"
        f"{CONTAINER_NAME}/ScottAdams.xml"
    )


if __name__ == "__main__":
    main()
