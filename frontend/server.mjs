import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(here);
const dist = path.join(here, "dist");
const host = process.env.DRIVEMATE_FRONTEND_HOST || "127.0.0.1";
const port = Number(process.env.DRIVEMATE_FRONTEND_PORT || 8501);
const backend = new URL(process.env.DRIVEMATE_BACKEND_URL || "http://127.0.0.1:8000");
const token = process.env.DRIVEMATE_API_TOKEN || "";

const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml" };

function serve(res, file) {
  fs.readFile(file, (error, data) => {
    if (error) { res.writeHead(404); res.end("Not found"); return; }
    res.writeHead(200, { "Content-Type": mime[path.extname(file)] || "application/octet-stream", "Cache-Control": file.endsWith("index.html") ? "no-store" : "public, max-age=3600" });
    res.end(data);
  });
}

function proxy(req, res) {
  const upstream = http.request({ hostname: backend.hostname, port: backend.port, path: req.url, method: req.method, headers: { ...req.headers, host: backend.host, authorization: `Bearer ${token}` } }, (response) => {
    res.writeHead(response.statusCode || 502, response.headers);
    response.pipe(res);
  });
  upstream.on("error", () => { res.writeHead(502, { "Content-Type": "application/json" }); res.end(JSON.stringify({ message: "DriveMate 后端未连接" })); });
  req.pipe(upstream);
}

http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === "/health" || url.pathname.startsWith("/api/")) return proxy(req, res);
  if (url.pathname.startsWith("/assets/figma-hmi/")) return serve(res, path.join(root, url.pathname));
  const requested = path.normalize(path.join(dist, url.pathname));
  const file = requested.startsWith(dist) && fs.existsSync(requested) && fs.statSync(requested).isFile() ? requested : path.join(dist, "index.html");
  serve(res, file);
}).listen(port, host, () => console.log(`DriveMate web ready at http://${host}:${port}`));
