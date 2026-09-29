// Phase 7e — cluster-internal E2E (run from an ingestion pod, §12.26: it owns the flow).
//   kubectl exec -i <ingestion-pod> -- sh -c 'E2E_TOKEN=$(cat) node /tmp/e2e7e.mjs'  < token
// Token comes from a real authService /login (minted off7e user); shredded afterwards.
// Covers: /health, presign, direct-to-MinIO PUT, intent status, commit (202), duplicate
// (200 {duplicate:true}), unknown department (400), missing required payload field (400),
// event status. Topic→worker→row verification happens out-of-band (worker/DB own those hops).
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
const put = await fetch(up.url, {
  method: 'PUT',
  body: Buffer.from('e2e-media-bytes-7e'),
  headers: { 'content-type': 'image/jpeg' },
});
out.mediaPut = { status: put.status };

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
