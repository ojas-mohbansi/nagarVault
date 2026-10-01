// Phase 7e — cluster-internal E2E (run from an ingestion pod, §12.26: it owns the flow).
//   kubectl exec -i <ingestion-pod> -- sh -c 'E2E_TOKEN=$(cat) NODE_PATH=/app/node_modules node /tmp/e2e7e.mjs'  < token
// Token comes from a real authService /login (minted off7e user); shredded afterwards.
// Covers: /health, presign, direct-to-MinIO PUT, intent status, commit (202), duplicate
// (200 {duplicate:true}), unknown department (400), missing required payload field (400),
// event status. Topic→worker→row verification happens out-of-band (worker/DB own those hops).
//
// NOTE (ADR-025): with PRESIGN_PUBLIC_URL set, the API mints browser-facing URLs whose host is
// intentionally unreachable from inside the cluster. The media leg then re-mints an equivalent
// in-cluster presigned URL for the same objectKey using the pod's own SDK + credentials env
// (require() below needs the NODE_PATH in the invocation line); the literal browser-path proof
// is the Phase-8 Gate 4 run from the operator host.
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

async function internalPutUrl({ bucket, objectKey, contentType }) {
  const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');
  const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');
  const s3 = new S3Client({
    endpoint: process.env.MINIO_URL,
    region: 'us-east-1',
    forcePathStyle: true,
    credentials: { accessKeyId: process.env.MINIO_ACCESS_KEY, secretAccessKey: process.env.MINIO_SECRET_KEY },
  });
  return getSignedUrl(s3, new PutObjectCommand({ Bucket: bucket, Key: objectKey, ContentType: contentType }), { expiresIn: 300 });
}

const BASE = 'http://localhost:3000';
const authorization = `Bearer ${process.env.E2E_TOKEN}`;
const call = async (path, opts = {}) => {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { 'content-type': 'application/json', authorization, ...(opts.headers || {}) },
  });
  let body;
  try { body = await r.json(); } catch { body = await r.text(); }
  return { status: r.status, body };
};

const out = {};
out.health = await call('/health');

const filename = `e2e-${Date.now()}.jpg`;
const pr = await call('/api/v1/uploads/presign', {
  method: 'POST',
  body: JSON.stringify({ files: [{ filename, contentType: 'image/jpeg', size: 16 }] }),
});
out.presign = { status: pr.status, uploads: (pr.body.uploads || []).length, ttlSeconds: pr.body.ttlSeconds };

const up = pr.body.uploads?.[0];
if (!up) { console.log('PRESIGN-FAIL ' + JSON.stringify(pr)); process.exit(2); }
let mediaUrl = up.url;
let mediaUrlSource = 'api';
if (process.env.PRESIGN_PUBLIC_URL && up.url.startsWith(process.env.PRESIGN_PUBLIC_URL)) {
  mediaUrl = await internalPutUrl({ bucket: up.bucket, objectKey: up.objectKey, contentType: 'image/jpeg' });
  mediaUrlSource = 'internal-re-mint';
}
const put = await fetch(mediaUrl, {
  method: 'PUT',
  body: Buffer.from('e2e-media-bytes-7e'),
  headers: { 'content-type': 'image/jpeg' },
});
out.mediaPut = { status: put.status, urlSource: mediaUrlSource };

out.intentStatus = await call(`/api/v1/uploads/${up.attachmentId}`);

const rid = `e2e-7e-${Date.now()}`;
const eventBody = {
  department: 'complaints',
  sourceSystem: 'e2e',
  sourceRecordId: rid,
  occurredAt: new Date().toISOString(),
  payload: { ward: '1', category: 'sanitation', status: 'open', description: 'E2E phase-7e overflow near market road' },
  attachments: [{ attachmentId: up.attachmentId }],
};
out.commit = await call('/api/v1/events', { method: 'POST', body: JSON.stringify(eventBody) });
out.duplicate = await call('/api/v1/events', { method: 'POST', body: JSON.stringify(eventBody) });

out.unknownDepartment = await call('/api/v1/events', {
  method: 'POST',
  body: JSON.stringify({ department: 'police', sourceSystem: 'e2e', sourceRecordId: `${rid}-b1`, occurredAt: new Date().toISOString(), payload: {} }),
});
out.missingDescription = await call('/api/v1/events', {
  method: 'POST',
  body: JSON.stringify({ department: 'complaints', sourceSystem: 'e2e', sourceRecordId: `${rid}-b2`, occurredAt: new Date().toISOString(), payload: { ward: '2' } }),
});

out.eventStatus = await call(`/api/v1/events/${out.commit.body.eventId}`);

console.log('E2E-RESULT ' + JSON.stringify(out, null, 1));
