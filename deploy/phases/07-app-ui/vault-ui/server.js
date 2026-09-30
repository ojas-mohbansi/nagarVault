// vault-ui mock-data injector — Phase 7g. Dev overlay per CONVENTIONS §4 (5173, never
// edge-exposed). Plain Node http (no framework dep). The form POSTs to this server,
// which proxies ONLY the allowlisted ingestion calls server-side (ingestion has no
// CORS middleware pre-Phase-8). Auth: the operator stages a session token at
// /tmp/injector-token (ephemeral, shredded after use) — the browser still never holds
// it; the relay is server-side.
import http from 'node:http';
import { readFileSync } from 'node:fs';
import {
  INGESTION_BASE_DEFAULT,
  isProxyable,
  redactForLog,
  resolveTarget,
} from './src/lib/proxy.js';

const PORT = 5173;
const BASE = process.env.INGESTION_URL || INGESTION_BASE_DEFAULT;
const TOKEN_PATH = '/tmp/injector-token';

const page = () => `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>NagarVault injector (dev)</title>
<style>body{font-family:system-ui;max-width:42rem;margin:3rem auto;padding:0 1rem;color:#111}
input,button{display:block;width:100%;padding:.55rem;margin:.35rem 0;box-sizing:border-box}
button{background:#0a7d33;color:#fff;border:0;border-radius:6px;cursor:pointer}
pre{background:#f4f4f4;padding:.8rem;border-radius:6px;overflow-x:auto;white-space:pre-wrap}
h1{font-size:1.2rem}</style></head>
<body>
<h1>NagarVault mock-data injector (dev overlay)</h1>
<p>Posts a synthetic citizen complaint to the ingestion API (department <code>complaints</code>,
source system <code>vault-ui</code>). The ingestion API validates and publishes to the
frozen raw topic; the enrich worker then upserts it.</p>
<form id="f">
<label>Ward <input name="ward" value="1"></label>
<label>Description <input name="description" value="Overflow near market road"></label>
<button>Inject event</button>
</form>
<pre id="out">Result appears here.</pre>
<script>
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const r = await fetch('/inject/complaint', { method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ward: fd.get('ward'), description: fd.get('description') }) });
  const j = await r.json().catch(() => ({}));
  document.getElementById('out').textContent = r.status + ' ' + JSON.stringify(j, null, 2);
};
</script>
</body></html>`;

function bearer() {
  try {
    const t = readFileSync(TOKEN_PATH, 'utf8').trim();
    return t ? `Bearer ${t}` : null;
  } catch {
    return null;
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (req.method === 'GET' && url.pathname === '/') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    return res.end(page());
  }
  if (req.method === 'POST' && url.pathname === '/inject/complaint') {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    let body;
    try {
      body = JSON.parse(raw || '{}');
    } catch {
      res.writeHead(400, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ detail: 'invalid JSON' }));
    }
    const authz = bearer();
    if (!authz) {
      res.writeHead(503, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ detail: 'no staged token: write /tmp/injector-token' }));
    }
    if (!isProxyable('POST', '/api/v1/events')) {
      res.writeHead(403, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ detail: 'not proxyable' }));
    }
    const { syntheticComplaint } = await import('./src/lib/proxy.js');
    const rid = `ui-${Date.now()}`;
    let event;
    try {
      event = syntheticComplaint({ ...body, sourceRecordId: rid });
    } catch (e) {
      res.writeHead(400, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ detail: e.message }));
    }
    const target = resolveTarget(BASE, '/api/v1/events');
    const upstream = await fetch(target, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: authz },
      body: JSON.stringify(event),
    });
    const payload = await upstream.json().catch(() => ({}));
    console.log(`injector ${req.method} ${url.pathname} -> ${upstream.status} via ${target} headers=${JSON.stringify(redactForLog({ authorization: authz }))}`);
    res.writeHead(upstream.status, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ sourceRecordId: rid, ...payload }));
  }
  res.writeHead(404, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ detail: 'not found' }));
});

server.listen(PORT, '0.0.0.0', () => console.log(`vault-ui injector on ${PORT} -> ${BASE}`));

const shutdown = () => {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 2000);
};
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
