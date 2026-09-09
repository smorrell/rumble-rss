const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOST = "0.0.0.0";
const PORT = Number(process.env.PORT) || 3000;
const repoPath = __dirname;
const audioDir = path.join(repoPath, "mp3s");
const metadataPath = path.join(audioDir, "video_metadata.json");
const networkAddresses = Object.values(os.networkInterfaces())
  .flat()
  .filter((details) => details.family === "IPv4" && !details.internal)
  .map((details) => details.address);

function sendError(response, statusCode, message) {
  response.writeHead(statusCode, {
    "Content-Type": "text/plain; charset=utf-8",
  });
  response.end(`${message}\n`);
}

function serveFile(request, response, filePath, contentType, missingMessage) {
  fs.stat(filePath, (error, stats) => {
    if (error || !stats.isFile()) {
      sendError(response, 404, missingMessage);
      return;
    }

    response.writeHead(200, {
      "Content-Type": contentType,
      "Content-Length": stats.size,
      "Cache-Control": "no-cache",
    });

    if (request.method === "HEAD") {
      response.end();
      return;
    }

    fs.createReadStream(filePath).pipe(response);
  });
}

function escapeXml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function formatPublishedDate(uploadDate) {
  if (!/^\d{8}$/.test(uploadDate || "")) {
    return new Date().toUTCString();
  }

  const year = Number(uploadDate.slice(0, 4));
  const month = Number(uploadDate.slice(4, 6)) - 1;
  const day = Number(uploadDate.slice(6, 8));
  return new Date(Date.UTC(year, month, day)).toUTCString();
}

function buildFeed(request) {
  const metadata = fs.existsSync(metadataPath)
    ? JSON.parse(fs.readFileSync(metadataPath, "utf8"))
    : {};
  const baseUrl = `http://${request.headers.host || "localhost"}`;
  const items = fs.existsSync(audioDir)
    ? fs
        .readdirSync(audioDir)
        .filter((fileName) => fileName.endsWith(".mp3"))
        .map((fileName) => {
          const filePath = path.join(audioDir, fileName);
          const fileSize = fs.statSync(filePath).size;
          const videoId =
            Object.keys(metadata).find(
              (id) => metadata[id].filename === fileName,
            ) || path.parse(fileName).name;
          const entry = metadata[videoId] || {};
          const audioUrl = `${baseUrl}/mp3s/${encodeURIComponent(fileName)}`;

          return `
    <item>
      <title>${escapeXml(entry.title || `Episode ${videoId}`)}</title>
      <description>${escapeXml(entry.description || "")}</description>
      <pubDate>${formatPublishedDate(entry.upload_date)}</pubDate>
      <guid isPermaLink="false">${escapeXml(videoId)}</guid>
      <enclosure url="${escapeXml(audioUrl)}" length="${fileSize}" type="audio/mpeg" />
    </item>`;
        })
        .join("")
    : "";

  return `<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>My Rumble Podcast</title>
    <link>https://rumble.com/</link>
    <description>Audio mirrors of my favorite Rumble channel.</description>${items}
  </channel>
</rss>
`;
}

function serveFeed(request, response) {
  try {
    const feed = buildFeed(request);
    response.writeHead(200, {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Content-Length": Buffer.byteLength(feed),
      "Cache-Control": "no-cache",
    });
    response.end(request.method === "HEAD" ? undefined : feed);
  } catch (error) {
    sendError(response, 500, `Unable to build feed: ${error.message}`);
  }
}

const server = http.createServer((request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end("Method Not Allowed\n");
    return;
  }

  const requestPath = new URL(request.url, `http://${request.headers.host}`)
    .pathname;

  if (requestPath === "/" || requestPath === "/feed.xml") {
    serveFeed(request, response);
    return;
  }

  if (requestPath.startsWith("/mp3s/")) {
    const fileName = decodeURIComponent(requestPath.slice("/mp3s/".length));
    if (
      !fileName ||
      path.basename(fileName) !== fileName ||
      !fileName.endsWith(".mp3")
    ) {
      sendError(response, 404, "Audio file not found.");
      return;
    }

    serveFile(
      request,
      response,
      path.join(repoPath, "mp3s", fileName),
      "audio/mpeg",
      "Audio file not found.",
    );
    return;
  }

  sendError(response, 404, "Not Found");
});

server.listen(PORT, HOST, () => {
  const feedUrls = (networkAddresses.length ? networkAddresses : ["localhost"])
    .map((address) => `http://${address}:${PORT}/feed.xml`)
    .join(", ");
  console.log(`Feed URL(s): ${feedUrls}`);
});

server.on("error", (error) => {
  console.error(`Server error: ${error.message}`);
  process.exitCode = 1;
});
