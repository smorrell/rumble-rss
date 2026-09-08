const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOST = "0.0.0.0";
const PORT = Number(process.env.PORT) || 3000;
const repoPath = __dirname;
const feedPath = path.join(repoPath, "feed.xml");
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

const server = http.createServer((request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end("Method Not Allowed\n");
    return;
  }

  const requestPath = new URL(request.url, `http://${request.headers.host}`)
    .pathname;

  if (requestPath === "/" || requestPath === "/feed.xml") {
    serveFile(
      request,
      response,
      feedPath,
      "application/rss+xml; charset=utf-8",
      "feed.xml not found. Run the RSS pipeline first.",
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
    .map((address) => `http://${address}:${PORT}/feed.xml`)
    .join(", ");
  console.log(`Feed URL(s): ${feedUrls}`);
});

server.on("error", (error) => {
  console.error(`Server error: ${error.message}`);
  process.exitCode = 1;
});
