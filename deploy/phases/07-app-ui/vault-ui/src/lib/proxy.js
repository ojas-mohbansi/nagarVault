// vault-ui injector proxy pure logic — Phase 7g.
//
// The injector (5173, dev overlay, never edge-exposed per CONVENTIONS §4) serves a
// form that POSTs synthetic civic events to the ingestion API. The ingestion API has
// no CORS middleware before Phase 8, so the injector PROXIES server-side — but only a
// fixed allowlist, so it can never become an open relay inside the cluster.
export const INGESTION_BASE_DEFAULT =
  'http://ingestion.nagar-app.svc.cluster.local:3000';

const PROXYABLE = new Set([
  'GET /health',
  'POST /api/v1/events',
  'POST /api/v1/uploads/presign',
]);

export function resolveTarget(base, path) {
  if (!path || typeof path !== 'string') throw new Error('bad path');
  if (path.startsWith('//') || /^[a-z]+:\/\//i.test(path)) throw new Error('bad path');
  if (path.includes('..')) throw new Error('bad path');
  return new URL(path, base.replace(/\/$/, '') + '/').toString();
}

export function isProxyable(method, path) {
  if (typeof method !== 'string' || typeof path !== 'string') return false;
  const bare = path.split('?')[0];
  return PROXYABLE.has(`${method.toUpperCase()} ${bare}`);
}

export function redactForLog(headers) {
  const out = { ...headers };
  for (const k of Object.keys(out)) {
    if (/authorization|cookie/i.test(k)) out[k] = '<redacted>';
  }
  return out;
}

export function syntheticComplaint({ sourceRecordId, ward, description, category }) {
  if (!sourceRecordId || !description) throw new Error('sourceRecordId and description are required');
  return {
    department: 'complaints',
    sourceSystem: 'vault-ui',
    sourceRecordId: String(sourceRecordId),
    occurredAt: new Date().toISOString(),
    payload: {
      ward: String(ward ?? '1'),
      category: String(category ?? 'sanitation'),
      status: 'open',
      description: String(description),
    },
  };
}
