// Minimal fixture: serves an index page with an absolute asset path so the
// proxy has something meaningful to rewrite.
const http = require("http");

const port = Number(process.env.PORT || 4321);
console.log(`fixture listening on ${port}`);

http
  .createServer((req, res) => {
    if (req.url === "/api/ping") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ pong: true, path: req.url }));
      return;
    }
    if (req.url === "/style.css") {
      res.writeHead(200, { "content-type": "text/css" });
      res.end("body{background:#123}");
      return;
    }
    res.writeHead(200, { "content-type": "text/html" });
    res.end('<!doctype html><html><head><link rel="stylesheet" href="/style.css"></head><body>fixture-ok</body></html>');
  })
  .listen(port, "127.0.0.1");
