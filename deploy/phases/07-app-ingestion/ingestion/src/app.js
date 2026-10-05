// ingestion backend — Express API (port 3000), Phase 7e fresh rebuild (ADR-013).
//
// CONTRACTS (verbatim — ARCHITECTURE §4.1 endpoint registry; §3.2 ingestion invariants;
// §4.2 topic registry; the 7c wire envelope from the worker):
//   POST /api/v1/uploads/presign   JWT; mint presigned PUTs + store intents (TTL 600s)
//   GET  /api/v1/uploads/:id       JWT; intent status
//   POST /api/v1/events            JWT; verify attachments server-side (statObject), build
//                                  the 7c envelope, publish to the SERVER-CHOSEN topic;
//                                  202 accepted | 200 {duplicate:true} (§3.2)
//   GET  /api/v1/events/:eventId   JWT; event status
//   GET  /health                   public; {api, minio, kafka} shape
//
// §3.2 invariants enforced here: the API never proxies media bytes (presigned PUTs direct
// to MinIO; only bucket/objectKey references travel); clients cannot choose topics;
// duplicates on sourceSystem+sourceRecordId answered idempotently (200 duplicate).
//
// Infrastructure is behind the injectable seams on globalThis.__ingestion (set by
// src/runtime.js in production, by tests in-memory): presignUrls, statObject, redisSet/
// redisGet/redisExpire, kafkaSend.
import crypto from 'node:crypto';
import express from 'express';
import jwt from 'jsonwebtoken';
import { buildEnvelope, dedupKey, routeFor, TOPIC_ROUTES } from './envelope.js';

const ISSUER = 'nagar-auth';
const AUDIENCE = 'nagar-services';
const UPLOAD_TTL_S = parseInt(process.env.UPLOAD_TTL_S || '600', 10);
const MAX_BODY = '256kb';

const deps = () => globalThis.__ingestion;

function requireJwt(req, res, next) {
  const header = req.headers.authorization || '';
  const token = header.toLowerCase().startsWith('bearer ') ? header.slice(7).trim() : null;
  if (!token) return res.status(401).json({ detail: 'missing session' });
  try {
    req.claims = jwt.verify(token, process.env.JWT_SECRET, {
      algorithms: ['HS256'], audience: AUDIENCE, issuer: ISSUER,
    });
    return next();
  } catch {
    return res.status(401).json({ detail: 'invalid or expired session' });
  }
}

function buildApp() {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: MAX_BODY }));

  app.get('/', (_req, res) => res.json({ status: 'ok', service: 'ingestion' }));

  app.get('/health', async (_req, res) => {
    const d = deps();
    const checks = { api: true, minio: false, kafka: false };
    try { checks.minio = await d.minioOk(); } catch { checks.minio = false; }
    try { checks.kafka = await d.kafkaOk(); } catch { checks.kafka = false; }
    const ok = checks.minio && checks.kafka;
    res.status(ok ? 200 : 503).json(checks);
  });

  app.post('/api/v1/uploads/presign', requireJwt, async (req, res) => {
    const files = req.body?.files;
    if (!Array.isArray(files) || files.length === 0 || files.length > 20) {
      return res.status(400).json({ detail: 'files must be a non-empty array (max 20)' });
    }
    for (const f of files) {
      if (!f?.filename || !f?.contentType) return res.status(400).json({ detail: 'each file needs filename + contentType' });
    }
    const d = deps();
    const uploads = [];
    for (const f of files) {
      const attachmentId = crypto.randomUUID();
      const objectKey = `events/${attachmentId}/${f.filename.replace(/[^a-zA-Z0-9._-]/g, '_')}`;
      const url = await d.presignUrls({ bucket: process.env.MEDIA_BUCKET || 'raw-media', objectKey, contentType: f.contentType });
      await d.redisSet(`upload-intent:${attachmentId}`, JSON.stringify({
        bucket: process.env.MEDIA_BUCKET || 'raw-media', objectKey, contentType: f.contentType,
        size: f.size ?? null, subject: req.claims.sub, createdAt: Date.now(),
      }), UPLOAD_TTL_S);
      uploads.push({ attachmentId, bucket: process.env.MEDIA_BUCKET || 'raw-media', objectKey, url });
    }
    return res.status(201).json({ uploads, ttlSeconds: UPLOAD_TTL_S });
  });

  app.get('/api/v1/uploads/:attachmentId', requireJwt, async (req, res) => {
    const raw = await deps().redisGet(`upload-intent:${req.params.attachmentId}`);
    if (!raw) return res.status(404).json({ detail: 'unknown or expired intent' });
    return res.status(200).json({ status: 'pending', ttlSeconds: UPLOAD_TTL_S, ...JSON.parse(raw) });
  });

  app.post('/api/v1/events', requireJwt, async (req, res) => {
    const d = deps();
    const body = req.body || {};
    let topic;
    try { topic = routeFor(body.department); } catch { return res.status(400).json({ detail: 'unknown department' }); }

    const attachments = [];
    const consumedIntents = [];
    for (const a of body.attachments || []) {
      const raw = await d.redisGet(`upload-intent:${a.attachmentId}`);
      if (!raw) return res.status(409).json({ detail: `unknown or expired upload intent: ${a.attachmentId}` });
      const intent = JSON.parse(raw);
      try {
        const stat = await d.statObject({ bucket: intent.bucket, objectKey: intent.objectKey });
        attachments.push({ bucket: intent.bucket, objectKey: intent.objectKey, size: stat.size });
        consumedIntents.push(a.attachmentId); // consumed only once the event is published
      } catch {
        return res.status(409).json({ detail: `attachment not verifiable in object store: ${a.attachmentId}` });
      }
    }

    // §3.2 duplicate detection on sourceSystem + sourceRecordId, answered idempotently.
    const dupKey = `dedup:${dedupKey(body.sourceSystem, body.sourceRecordId)}`;
    if (!body.sourceSystem || !body.sourceRecordId) {
      return res.status(400).json({ detail: 'sourceSystem and sourceRecordId are required' });
    }
    const existing = await d.redisGet(dupKey);
    if (existing) {
      return res.status(200).json({ duplicate: true, eventId: existing });
    }

    let envelope;
    try {
      envelope = buildEnvelope({
        department: body.department,
        eventId: `evt-${crypto.randomUUID()}`,
        sourceSystem: body.sourceSystem,
        sourceRecordId: body.sourceRecordId,
        occurredAt: body.occurredAt,
        payload: body.payload,
        attachments,
      });
    } catch (e) {
      return res.status(400).json({ detail: e.message });
    }
    if (!body.occurredAt) return res.status(400).json({ detail: 'occurredAt is required' });

    await d.kafkaSend(topic, envelope.eventId, JSON.stringify(envelope));
    await d.redisSet(dupKey, envelope.eventId, UPLOAD_TTL_S);
    await d.redisSet(`event:${envelope.eventId}`, JSON.stringify({ topic, dedupKey: dedupKey(body.sourceSystem, body.sourceRecordId), publishedAt: Date.now() }), UPLOAD_TTL_S);
    // The intents are shortened only now: a request refused above (validation, dedup,
    // unverifiable attachment) must leave the 600s upload window untouched so the
    // operator can correct the body and retry without re-uploading media.
    for (const attachmentId of consumedIntents) {
      await d.redisExpire(`upload-intent:${attachmentId}`, 60); // consumed; brief grace for retries
    }
    return res.status(202).json({ eventId: envelope.eventId, topic });
  });

  app.get('/api/v1/events/:eventId', requireJwt, async (req, res) => {
    const raw = await deps().redisGet(`event:${req.params.eventId}`);
    if (!raw) return res.status(404).json({ detail: 'unknown eventId' });
    const meta = JSON.parse(raw);
    return res.status(200).json({ eventId: req.params.eventId, status: 'published', ...meta });
  });

  return app;
}

export { buildApp, TOPIC_ROUTES };

// Shared-hub registration (see src/envelope.js): tests call createApp() after
// monkeypatching the seams.
globalThis.__ingestion = Object.assign(globalThis.__ingestion || {}, {
  createApp: buildApp,
});
