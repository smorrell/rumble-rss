const http = require("http");
const fs = require("fs");
const path = require("path");

const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT) || 3000;
const feedPath = path.join(__dirname, "your-local-github-repo", "feed.xml");

const server = http.createServer((request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end("Method Not Allowed\n");
    return;
  }

  if (request.url !== "/" && request.url !== "/feed.xml") {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not Found\n");
    return;
  }

  fs.stat(feedPath, (error, stats) => {
    if (error || !stats.isFile()) {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("feed.xml not found. Run the RSS pipeline first.\n");
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
});

server.listen(PORT, HOST, () => {
  console.log(`Serving feed.xml at http://${HOST}:${PORT}/feed.xml`);
});

server.on("error", (error) => {
  console.error(`Server error: ${error.message}`);
  process.exitCode = 1;
});
