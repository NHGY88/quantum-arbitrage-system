/**
 * Web Client (Express) - Port 3000
 *
 * Serves the responsive dark terminal (m.html / accounts.html) and proxies
 * every /api/* call to the Admin Server on Port 8000.
 *
 * Same-origin proxying is deliberate: it keeps the browser free of CORS
 * preflights, keeps the Admin host/port invisible to the client, and means
 * the token is only ever sent to a single origin.
 */

const path = require("path");
const { Readable } = require("stream");
const express = require("express");

const PORT = Number(process.env.WEB_PORT || 3000);
const ADMIN_URL = process.env.ADMIN_URL || "http://127.0.0.1:8000";

const app = express();
app.disable("x-powered-by");

// --- same-origin API proxy -----------------------------------------------

app.use("/api", async (req, res) => {
  const target = `${ADMIN_URL}/api${req.url}`;
  try {
    // JSON bodies are parsed by the tiny reader below; multipart/form-data
    // (screenshot uploads) must stay a raw stream so the boundary header is
    // preserved when we hand it to fetch().
    const ct = req.headers["content-type"] || "";
    const isMultipart = ct.startsWith("multipart/form-data");

    let body;
    if (!isMultipart && req.method !== "GET" && req.method !== "HEAD") {
      const chunks = [];
      let total = 0;
      for await (const chunk of req) {
        total += chunk.length;
        if (total > 2 * 1024 * 1024) {
          res.status(413).json({ detail: "payload too large" });
          return;
        }
        chunks.push(chunk);
      }
      if (chunks.length) body = Buffer.concat(chunks);
    }

    const headers = {};
    if (ct) headers["content-type"] = ct;
    if (req.headers.authorization) headers.authorization = req.headers.authorization;

    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body: ["GET", "HEAD"].includes(req.method)
        ? undefined
        : isMultipart
          ? Readable.toWeb(req)
          : (body ?? Buffer.alloc(0)),
      duplex: "half",
    });

    const buf = Buffer.from(await upstream.arrayBuffer());
    res.status(upstream.status);
    res.set("content-type", upstream.headers.get("content-type") || "application/json");
    res.send(buf);
  } catch (err) {
    res.status(502).json({
      detail: "admin server unreachable",
      admin_url: ADMIN_URL,
      error: String(err && err.message ? err.message : err),
    });
  }
});

// Health passthrough (not under /api so the dashboard can poll it cheaply)
app.get("/health", async (_req, res) => {
  try {
    const r = await fetch(`${ADMIN_URL}/health`);
    res.status(r.status).json(await r.json());
  } catch {
    res.status(502).json({ status: "unreachable", admin_url: ADMIN_URL });
  }
});

// --- static terminal -----------------------------------------------------

app.use(express.static(path.join(__dirname, "public"), { extensions: ["html"] }));

app.get("/", (_req, res) => res.sendFile(path.join(__dirname, "public", "m.html")));

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[web] listening on http://0.0.0.0:${PORT} -> admin ${ADMIN_URL}`);
});