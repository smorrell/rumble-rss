const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOST = process.env.HOST || "0.0.0.0";
const PORT = Number(process.env.PORT) || 3000;
const repoPath = __dirname;
const feedPath = path.join(repoPath, "AnnCoulter.xml");
const audioDir = path.join(repoPath, "mp3s");

function logRequest(request, response, startTime) {
  const requestPath = new URL(
    request.url,
    `http://${request.headers.host || "localhost"}`,
  ).pathname;
  const duration = Date.now() - startTime;
  const contentLength = response.getHeader("Content-Length") || 0;
  console.log(
    `${new Date().toISOString()} ${request.method} ${requestPath} ` +
      `${response.statusCode} ${contentLength} bytes ${duration}ms`,
  );
}

function sendText(response, statusCode, message) {
  response.writeHead(statusCode, {
    "Content-Type": "text/plain; charset=utf-8",
  });
  response.end(`${message}\n`);
}

function serveFeed(request, response) {
  fs.stat(feedPath, (error, stats) => {
    if (error || !stats.isFile()) {
      sendText(response, 404, "AnnCoulter.xml not found.");
      return;
    }

    response.writeHead(200, {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Content-Length": stats.size,
      "Cache-Control": "no-cache",
    });
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    fs.createReadStream(feedPath).pipe(response);
  });
}

function listedAudioFiles() {
  const feed = fs.readFileSync(feedPath, "utf8");
  const files = new Set();
  const enclosurePattern = /<enclosure\b[^>]*\burl=["']([^"']+)["'][^>]*>/gi;
  let match;

  while ((match = enclosurePattern.exec(feed)) !== null) {
    const enclosureUrl = new URL(match[1], "http://localhost/");
    const enclosurePath = decodeURIComponent(enclosureUrl.pathname);
    const prefix = "/mp3s/";
    if (enclosurePath.startsWith(prefix)) {
      const fileName = enclosurePath.slice(prefix.length);
      if (
        fileName &&
        path.basename(fileName) === fileName &&
        fileName.endsWith(".mp3")
      ) {
        files.add(fileName);
      }
    }
  }
  return files;
}

function serveAudio(request, response, requestPath) {
  let fileName;
  try {
    fileName = decodeURIComponent(requestPath.slice("/mp3s/".length));
  } catch {
    sendText(response, 400, "Invalid audio path.");
    return;
  }

  if (
    !fileName ||
    path.basename(fileName) !== fileName ||
    !fileName.endsWith(".mp3")
  ) {
    sendText(response, 404, "Audio file not found.");
    return;
  }

  let allowedFiles;
  try {
    allowedFiles = listedAudioFiles();
  } catch (error) {
    sendText(response, 500, `Unable to read AnnCoulter.xml: ${error.message}`);
    return;
  }
  if (!allowedFiles.has(fileName)) {
    sendText(response, 404, "Audio file is not listed in AnnCoulter.xml.");
    return;
  }

  const filePath = path.join(audioDir, fileName);
  fs.stat(filePath, (error, stats) => {
    if (error || !stats.isFile()) {
      sendText(response, 404, "Audio file not found.");
      return;
    }

    const headers = {
      "Content-Type": "audio/mpeg",
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-cache",
    };
    const range = request.headers.range;
    if (!range) {
      response.writeHead(200, { ...headers, "Content-Length": stats.size });
      if (request.method === "HEAD") response.end();
      else fs.createReadStream(filePath).pipe(response);
      return;
    }

    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (!match) {
      response.writeHead(416, { "Content-Range": `bytes */${stats.size}` });
      response.end();
      return;
    }

    const start = match[1]
      ? Number(match[1])
      : Math.max(stats.size - Number(match[2]), 0);
    const end = match[2] ? Number(match[2]) : stats.size - 1;
    if (
      !Number.isInteger(start) ||
      !Number.isInteger(end) ||
      start < 0 ||
      start > end ||
      end >= stats.size
    ) {
      response.writeHead(416, { "Content-Range": `bytes */${stats.size}` });
      response.end();
      return;
    }

    response.writeHead(206, {
      ...headers,
      "Content-Length": end - start + 1,
      "Content-Range": `bytes ${start}-${end}/${stats.size}`,
    });
    if (request.method === "HEAD") response.end();
    else fs.createReadStream(filePath, { start, end }).pipe(response);
  });
}

const server = http.createServer((request, response) => {
  const startTime = Date.now();
  response.on("finish", () => logRequest(request, response, startTime));

  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end("Method Not Allowed\n");
    return;
  }

  const requestPath = new URL(
    request.url,
    `http://${request.headers.host || "localhost"}`,
  ).pathname;
  if (requestPath === "/" || requestPath === "/AnnCoulter.xml") {
    serveFeed(request, response);
  } else if (requestPath.startsWith("/mp3s/")) {
    serveAudio(request, response, requestPath);
  } else {
    sendText(response, 404, "Not Found");
  }
});

server.listen(PORT, HOST, () => {
  const address =
    Object.values(os.networkInterfaces())
      .flat()
      .find((details) => details.family === "IPv4" && !details.internal)
      ?.address || "localhost";
  console.log(`Ann Coulter RSS feed: http://${address}:${PORT}/AnnCoulter.xml`);
  console.log(`Server listening on ${HOST}:${PORT}`);
});
