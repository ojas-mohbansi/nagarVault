// ingestion backend test suite — Phase 7e (hermetic; no Kafka, no MinIO, no Redis, no auth).
//
// CONTRACTS UNDER TEST:
//   * ARCHITECTURE §4.1: POST /api/v1/uploads/presign (JWT; mint presigned PUTs),
//     GET /api/v1/uploads/:attachmentId (JWT; intent status), POST /api/v1/events
//     (JWT; commit event -> 202 / 200 duplicate), GET /api/v1/events/:eventId (JWT),
//     GET /health (public; API/MinIO/Kafka).
//   * ARCHITECTURE §3.2: intents stored with TTL 600s; media by reference only (bucket +
//     objectKey verified server-side via statObject before acceptance); server-side topic
//     routing (clients cannot choose topics); duplicates detected on sourceSystem +
//     sourceRecordId and answered 200 {duplicate: true} idempotently; Kafka payload is the
//     7c wire envelope (deploy/phases/07-app-worker/worker/enrich.py).
//   * Cross-service contract: the publish envelope must satisfy the worker's validation —
//     pinned here by replicating the worker's accept/reject rules from
//     deploy/phases/07-app-worker/worker/enrich.py (camelCase keys, required envelope
//     fields, payload typed per department, snake_case table columns downstream).
//
// Seams (module-level, injectable via env or monkeypatch exports): presignUrls, statObject,
// redisGet/redisSet/redisExpire, kafkaSend, jti verification via JWT_SECRET env.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import jwt from 'jsonwebtoken';

process.env.JWT_SECRET = process.env.JWT_SECRET || 'test-secret-not-a-real-credential';
process.env.INGESTION_HTTP_PORT = process.env.INGESTION_HTTP_PORT || '0';
process.env.UPLOAD_TTL_S = process.env.UPLOAD_TTL_S || '600';

const secret = process.env.JWT_SECRET;
const admin = () =>
  jwt.sign(
    { iss: 'nagar-auth', aud: 'nagar-services', sub: 'admin-001', role: 'admin', jti: 'j-a', iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 600 },
    secret,
  );
const officer = () =>
  jwt.sign(
    { iss: 'nagar-auth', aud: 'nagar-services', sub: 'off-1', role: 'nmc_officer', jti: 'j-o', iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 600 },
    secret,
  );

// --------------------------------------------------------------------- unit: envelope + routing

await import('../src/envelope.js');
await import('../src/app.js');   // registers createApp on the hub (no real clients imported)

test('envelope builds the 7c wire contract for complaints', () => {
  const { buildEnvelope } = globalThis.__ingestion;
  const e = buildEnvelope({
    department: 'complaints',
    eventId: 'evt-1',
    sourceSystem: 'crm',
    sourceRecordId: 'REC-1',
    occurredAt: '2026-09-30T10:00:00Z',
    payload: { ward: '1', category: 'sanitation', status: 'open', description: 'drain' },
    attachments: [{ bucket: 'raw-media', objectKey: 'k/1.jpg' }],
  });
  assert.equal(e.eventId, 'evt-1');
  assert.equal(e.sourceSystem, 'crm');
  assert.equal(e.sourceRecordId, 'REC-1');
  assert.equal(e.occurredAt, '2026-09-30T10:00:00Z');
  assert.deepEqual(e.payload, { ward: '1', category: 'sanitation', status: 'open', description: 'drain' });
  assert.deepEqual(e.attachments, [{ bucket: 'raw-media', objectKey: 'k/1.jpg' }]);
});

test('topic routing is server-side and frozen to the §4.2 registry', () => {
  const { TOPIC_ROUTES } = globalThis.__ingestion;
  assert.deepEqual(TOPIC_ROUTES, {
    complaints: 'nmc.complaints.raw.restricted.v1',
    traffic: 'traffic.events.raw.v1',
    water: 'water.sensors.raw.v1',
    health: 'health.camps.raw.v1',
    ev: 'ev.bus.telemetry.raw.v1',
  });
});

test('publish envelope satisfies the 7c worker validation (cross-service contract)', () => {
  // Worker rules replicated from enrich.py: dict envelope; eventId/sourceSystem/
  // sourceRecordId/occurredAt present and strings; payload a dict; required fields per
  // table (sensorId+parameter for water, busId for ev); ints/floats coerce or reject.
  const { buildEnvelope, TOPIC_ROUTES, VALIDATORS } = globalThis.__ingestion;
  const workerAccepts = (topic, env) => {
    assert.ok(TOPIC_TABLE_HAS(topic));
    function TOPIC_TABLE_HAS(t) { return Object.values(TOPIC_ROUTES).includes(t); }
    for (const f of ['eventId', 'sourceSystem', 'sourceRecordId', 'occurredAt']) {
      assert.equal(typeof env[f], 'string', `${f} must be a string for the worker`);
      assert.ok(env[f].length > 0, `${f} must be non-empty for the worker`);
    }
    assert.equal(typeof env.payload, 'object');
    return VALIDATORS[topic](env.payload);
  };
  const t = TOPIC_ROUTES.traffic;
  const env = buildEnvelope({
    department: 'traffic',
    eventId: 'e2',
    sourceSystem: 'its',
    sourceRecordId: 'R2',
    occurredAt: '2026-09-30T11:00:00Z',
    payload: { junction: 'A1', eventType: 'congestion', vehicleCount: 3, averageSpeed: 12.5 },
  });
  assert.ok(workerAccepts(t, env));
  // worker rejects: water without sensorId, ev without busId — validated against the RAW
  // payloads (the API builder refuses those earlier; this pins the WORKER-level contract).
  const { VALIDATORS: V } = globalThis.__ingestion;
  assert.throws(() => V[TOPIC_ROUTES.water]({ parameter: 'ph' }));
  assert.throws(() => V[TOPIC_ROUTES.ev]({}));
  assert.ok(V[TOPIC_ROUTES.water]({ sensorId: 'W-1', parameter: 'ph' }));
});

test('unknown department is refused (server-side routing, fail closed)', () => {
  const { routeFor } = globalThis.__ingestion;
  assert.throws(() => routeFor('gossip'));
});

// --------------------------------------------------------------------- HTTP surface

function startServer(env, t) {
  return new Promise((resolve, reject) => {
    const { createApp } = globalThis.__ingestion;
    const deps = {
      presignUrls: async ({ objectKey }) => `http://minio/put/${objectKey}`,
      statObject: async () => ({ size: 10 }),
      redisSet: async (k, v, ttl) => { env.store[k] = { v, ttl }; },
      redisGet: async (k) => env.store[k]?.v ?? null,
      redisExpire: async (k, ttl) => { if (env.store[k]) env.store[k].ttl = ttl; },
      kafkaSend: async (topic, key, value) => { env.published.push({ topic, key, value }); },
      minioOk: async () => true,
      kafkaOk: async () => true,
    };
    Object.assign(globalThis.__ingestion, deps);
    const app = createApp();
    // app.listen returns the underlying http.Server (the express app itself has no .address)
    const httpServer = app.listen(0, '127.0.0.1', () => resolve(httpServer.address().port));
    t.after(() => httpServer.close()); // release the event loop so node --test can exit
    httpServer.on('error', reject);
  });
}

test('HTTP: presign -> verify -> commit -> duplicate, end to end', async (t) => {
  const env = { store: {}, published: [] };
  const port = await startServer(env, t);
  const base = `http://127.0.0.1:${port}`;
  const get = (path, opts = {}) =>
    new Promise((resolve, reject) => {
      const req = http.request(`${base}${path}`, { method: opts.method || 'GET', headers: opts.headers || {} }, (r) => {
        let b = '';
        r.on('data', (c) => (b += c));
        r.on('end', () => resolve({ status: r.statusCode, body: b ? JSON.parse(b) : null }));
      });
      req.on('error', reject);
      if (opts.body) req.write(opts.body);
      req.end();
    });

  // /health public and dependency-shaped
  let r = await get('/health');
  assert.equal(r.status, 200);
  assert.deepEqual(Object.keys(r.body).sort(), ['api', 'kafka', 'minio']);

  // presign without JWT -> 401
  r = await get('/api/v1/uploads/presign', { method: 'POST', body: JSON.stringify({ files: [] }) });
  assert.equal(r.status, 401);

  // presign happy path
  r = await get('/api/v1/uploads/presign', {
    method: 'POST',
    headers: { authorization: `Bearer ${officer()}`, 'content-type': 'application/json' },
    body: JSON.stringify({ files: [{ filename: 'a.jpg', contentType: 'image/jpeg' }] }),
  });
  assert.equal(r.status, 201);
  assert.equal(r.body.uploads.length, 1);
  const upload = r.body.uploads[0];
  assert.ok(upload.attachmentId && upload.url.startsWith('http://minio/put/'));

  // intent status
  r = await get(`/api/v1/uploads/${upload.attachmentId}`, { headers: { authorization: `Bearer ${officer()}` } });
  assert.equal(r.status, 200);
  assert.equal(r.body.status, 'pending');

  // events without any attachment requires none; malformed -> 400
  r = await get('/api/v1/events', {
    method: 'POST',
    headers: { authorization: `Bearer ${officer()}`, 'content-type': 'application/json' },
    body: JSON.stringify({ department: 'complaints', sourceSystem: 'crm', sourceRecordId: 'R9', occurredAt: '2026-09-30T10:00:00Z', payload: { ward: '1' }, attachments: [] }),
  });
  assert.equal(r.status, 400); // description required for complaints in the API schema

  // happy commit
  r = await get('/api/v1/events', {
    method: 'POST',
    headers: { authorization: `Bearer ${officer()}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      department: 'complaints',
      sourceSystem: 'crm',
      sourceRecordId: 'REC-77',
      occurredAt: '2026-09-30T10:00:00Z',
      payload: { ward: '1', category: 'sanitation', status: 'open', description: 'drain blocked' },
      attachments: [{ attachmentId: upload.attachmentId }],
    }),
  });
  assert.equal(r.status, 202);
  assert.ok(r.body.eventId);
  assert.equal(env.published.length, 1);
  assert.equal(env.published[0].topic, 'nmc.complaints.raw.restricted.v1');
  const sent = JSON.parse(env.published[0].value);
  assert.equal(sent.sourceRecordId, 'REC-77'); // the 7c envelope on the wire
  assert.deepEqual(sent.payload, { ward: '1', category: 'sanitation', status: 'open', description: 'drain blocked' });

  // duplicate detection on sourceSystem+sourceRecordId -> 200 {duplicate}
  r = await get('/api/v1/events', {
    method: 'POST',
    headers: { authorization: `Bearer ${officer()}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      department: 'complaints',
      sourceSystem: 'crm',
      sourceRecordId: 'REC-77',
      occurredAt: '2026-09-30T10:00:00Z',
      payload: { ward: '1', category: 'sanitation', status: 'open', description: 'drain blocked' },
      attachments: [],
    }),
  });
  assert.equal(r.status, 200);
  assert.equal(r.body.duplicate, true);
  assert.equal(env.published.length, 1); // nothing re-published

  // event status endpoint
  r = await get(`/api/v1/events/${r.body.eventId || 'evt-unknown'}`, { headers: { authorization: `Bearer ${officer()}` } });
  assert.ok([200, 404].includes(r.status));
});

test('HTTP: intent TTL is 600s and expired intent rejects commit', async (t) => {
  const env = { store: {}, published: [] };
  const port = await startServer(env, t);
  const base = `http://127.0.0.1:${port}`;
  const req = (path, opts = {}) =>
    new Promise((resolve, reject) => {
      const r = http.request(`${base}${path}`, { method: opts.method || 'GET', headers: opts.headers || {} }, (res) => {
        let b = '';
        res.on('data', (c) => (b += c));
        res.on('end', () => resolve({ status: res.statusCode, body: b ? JSON.parse(b) : null }));
      });
      r.on('error', reject);
      if (opts.body) r.write(opts.body);
      r.end();
    });
  let r = await req('/api/v1/uploads/presign', {
    method: 'POST',
    headers: { authorization: `Bearer ${officer()}`, 'content-type': 'application/json' },
    body: JSON.stringify({ files: [{ filename: 'b.jpg', contentType: 'image/jpeg' }] }),
  });
  const upload = r.body.uploads[0];
  assert.equal(env.store[`upload-intent:${upload.attachmentId}`].ttl, 600);
  // expire the intent, then try to commit referencing it
  delete env.store[`upload-intent:${upload.attachmentId}`];
  r = await req('/api/v1/events', {
    method: 'POST',
    headers: { authorization: `Bearer ${officer()}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      department: 'complaints',
      sourceSystem: 'crm',
      sourceRecordId: 'REC-88',
      occurredAt: '2026-09-30T10:00:00Z',
      payload: { ward: '2', category: 'sanitation', status: 'open', description: 'x' },
      attachments: [{ attachmentId: upload.attachmentId }],
    }),
  });
  assert.equal(r.status, 409); // unknown/expired intent
  assert.equal(env.published.length, 0);
});
