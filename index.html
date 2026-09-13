const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOST = "0.0.0.0";
const PORT = Number(process.env.PORT) || 3000;
const repoPath = __dirname;
const audioDir = path.join(repoPath, "mp3s");
const metadataPath = path.join(audioDir, "video_metadata.json");
const scottAdamsFeedPath = path.join(repoPath, "ScottAdams.xml");
const networkAddresses = Object.values(os.networkInterfaces())
  .flat()
  .filter((details) => details.family === "IPv4" && !details.internal)
  .map((details) => details.address);

function logRequest(request, response, startTime) {
  const duration = Date.now() - startTime;
  const requestPath = new URL(request.url, `http://${request.headers.host}`)
    .pathname;
  console.log(
    `${new Date().toISOString()} ${request.method} ${requestPath} ` +
      `${response.statusCode} ${duration}ms`,
  );
}

function sendError(response, statusCode, message) {
  response.writeHead(statusCode, {
    "Content-Type": "text/plain; charset=utf-8",
  });
  response.end(`${message}\n`);
}

function serveFile(request, response, filePath, contentType, missingMessage) {
  fs.stat(filePath, (error, stats) => {
    if (error || !stats.isFile()) {
      console.warn(`File not found: ${filePath}`);
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
          console.log(
            `Adding feed item: id=${videoId}, title=${entry.title || `Episode ${videoId}`}, ` +
              `file=${fileName}, size=${fileSize} bytes`,
          );

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

  console.log(
    `Built RSS feed with ${items ? items.split("<item>").length - 1 : 0} item(s).`,
  );

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
    console.error(`Feed generation failed: ${error.message}`);
    sendError(response, 500, `Unable to build feed: ${error.message}`);
  }
}

const server = http.createServer((request, response) => {
  const startTime = Date.now();
  response.on("finish", () => logRequest(request, response, startTime));

  if (request.method !== "GET" && request.method !== "HEAD") {
    console.warn(`Rejected HTTP method: ${request.method}`);
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

  if (requestPath === "/ScottAdams.xml") {
    serveFile(
      request,
      response,
      scottAdamsFeedPath,
      "application/rss+xml; charset=utf-8",
      "Scott Adams feed not found.",
    );
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
    .flatMap((address) => [
      `http://${address}:${PORT}/feed.xml`,
      `http://${address}:${PORT}/ScottAdams.xml`,
    ])
    .join(", ");
  console.log(`Feed URL(s): ${feedUrls}`);
  console.log(`Rumble RSS server listening on ${HOST}:${PORT}`);
});

server.on("error", (error) => {
  console.error(`Server error: ${error.message}`);
  process.exitCode = 1;
});
