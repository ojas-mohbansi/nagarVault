// Unit: the public presigned-URL adapter — Phase 7e (ADR-025; Phase-8 charter closure).
// Pure function; no clients, no network. Pins the two mechanical rules:
//   * the public origin replaces scheme+host (the SigV4 host is signed by the CALLER —
//     runtime.js presigns with a client pointed at PRESIGN_PUBLIC_URL, not with MINIO_URL);
//   * the frozen `/minio` route prefix (ADR-024 §5/§6) is inserted into the path; the
//     edge strip makes that prefix signature-neutral (MinIO verifies the native path).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { toPublicPresignedUrl } from '../src/presign-url.js';

const SIGNED =
  'http://minio.nagar-platform.svc.cluster.local:9000/raw-media/events/a1/x.bin' +
  '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Content-Sha256=UNSIGNED-PAYLOAD' +
  '&X-Amz-Credential=AKIAEXAMPLE%2F20261001%2Fus-east-1%2Fs3%2Faws4_request' +
  '&X-Amz-Signature=abcdef&X-Amz-SignedHeaders=host';

test('unset PRESIGN_PUBLIC_URL returns the signed URL untouched (legacy in-cluster behavior)', () => {
  assert.equal(toPublicPresignedUrl(SIGNED, ''), SIGNED);
});

test('public origin replaces scheme+host and the frozen /minio prefix is inserted', () => {
  const out = toPublicPresignedUrl(SIGNED, 'https://k3d.nagar.internal');
  assert.equal(
    out,
    'https://k3d.nagar.internal/minio/raw-media/events/a1/x.bin' +
      '?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Content-Sha256=UNSIGNED-PAYLOAD' +
      '&X-Amz-Credential=AKIAEXAMPLE%2F20261001%2Fus-east-1%2Fs3%2Faws4_request' +
      '&X-Amz-Signature=abcdef&X-Amz-SignedHeaders=host',
  );
});

test('a port on the public origin is preserved; trailing slashes are normalized', () => {
  const out = toPublicPresignedUrl(SIGNED, 'https://k3d.nagar.internal:8443/');
  assert.ok(out.startsWith('https://k3d.nagar.internal:8443/minio/raw-media/events/a1/x.bin?'));
});

test('the route prefix is configurable (runtime.js default stays /minio)', () => {
  const out = toPublicPresignedUrl(SIGNED, 'https://k3d.nagar.internal', '/store');
  assert.ok(out.startsWith('https://k3d.nagar.internal/store/raw-media/'));
});
