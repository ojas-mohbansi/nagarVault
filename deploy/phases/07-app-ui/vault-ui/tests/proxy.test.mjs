// vault-ui proxy tests — Phase 7g (hermetic; no node:http server, no network).
//
// CONTRACT UNDER TEST (CONVENTIONS §4: 5173 dev injector, never edge-exposed; the
// injector proxies to the ingestion API server-side because the ingestion API has no
// CORS middleware pre-Phase-8):
//   * only GET/POST are proxied; only a fixed allowlist of ingestion paths
//   * targets resolve under the configured INGESTION_URL base (no open proxy)
//   * authorization/session cookie headers are redacted from any log line
//   * the synthetic complaint event carries the documented envelope fields
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  resolveTarget,
  isProxyable,
  redactForLog,
  syntheticComplaint,
} from '../src/lib/proxy.js';

const BASE = 'http://ingestion.nagar-app.svc.cluster.local:3000';

test('resolveTarget joins the configured base with the allowlisted path', () => {
  assert.equal(
    resolveTarget(BASE, '/api/v1/events'),
    'http://ingestion.nagar-app.svc.cluster.local:3000/api/v1/events',
  );
});

test('resolveTarget refuses paths that escape the base or carry a scheme', () => {
  assert.throws(() => resolveTarget(BASE, 'http://evil.example/api'));
  assert.throws(() => resolveTarget(BASE, '/../../etc/passwd'));
  assert.throws(() => resolveTarget(BASE, '//evil.example/api'));
});

test('isProxyable allows exactly the documented method+path pairs', () => {
  assert.equal(isProxyable('POST', '/api/v1/events'), true);
  assert.equal(isProxyable('GET', '/health'), true);
  assert.equal(isProxyable('DELETE', '/api/v1/events'), false);
  assert.equal(isProxyable('GET', '/admin/secret'), false);
  assert.equal(isProxyable('POST', '/api/v1/uploads/presign'), true);
});

test('redactForLog strips credential material from header objects', () => {
  const headers = {
    authorization: 'Bearer abc', cookie: 'session_token=abc', 'content-type': 'application/json',
  };
  const out = redactForLog(headers);
  assert.equal(out.authorization, '<redacted>');
  assert.equal(out.cookie, '<redacted>');
  assert.equal(out['content-type'], 'application/json');
});

test('syntheticComplaint builds a valid complaints envelope body for the injector', () => {
  const body = syntheticComplaint({ sourceRecordId: 'ui-1', ward: '3', description: 'test' });
  assert.equal(body.department, 'complaints');
  assert.equal(body.sourceSystem, 'vault-ui');
  assert.equal(body.sourceRecordId, 'ui-1');
  assert.equal(body.payload.description, 'test');
  assert.ok(body.occurredAt);
});
