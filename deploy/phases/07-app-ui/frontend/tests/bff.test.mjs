// frontend BFF tests — Phase 7g (hermetic; no Next, no network).
//
// CONTRACT UNDER TEST (SECURITY §2 cookie semantics + §6.2 secret table; ARCHITECTURE
// §4.1 rows the BFF forwards to):
//   * session_token cookie value is relayed to auth/slm as `Bearer <token>` — the
//     browser never sees or sends a bearer token itself
//   * /api/login forwards ONLY {username, password} (the legacy `user_id` field is
//     gone from the current Credentials contract)
//   * Set-Cookie from authService is relayed so the session cookie stays host-only,
//     httponly, path=/ (the token never enters JS)
//   * /ask response is whitelisted to {sql, rows, row_count, role} (+ upstream detail
//     on failure) — no model internals leak
//   * upstream URLs resolve from env with frozen-registry defaults
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  bearerFromCookie,
  loginBody,
  askResponseWhitelist,
  upstreamFromEnv,
  cookiePairsFromSetCookie,
  logout,
} from '../src/lib/bff.js';

test('bearerFromCookie extracts the session token from a raw cookie header', () => {
  const header = 'other=1; session_token=abc.def.ghi; x=y';
  assert.equal(bearerFromCookie(header), 'abc.def.ghi');
});

test('bearerFromCookie returns null when absent or empty', () => {
  assert.equal(bearerFromCookie('other=1'), null);
  assert.equal(bearerFromCookie('session_token='), null);
  assert.equal(bearerFromCookie(undefined), null);
});

test('loginBody whitelists username+password and drops legacy fields', () => {
  const body = loginBody({ username: 'adm7f', password: 'pw', user_id: 'x', role: 'admin' });
  assert.deepEqual(body, { username: 'adm7f', password: 'pw' });
});

test('loginBody rejects non-object or missing credentials', () => {
  assert.throws(() => loginBody(null));
  assert.throws(() => loginBody({ username: 'a' }));
  assert.throws(() => loginBody({ password: 'b' }));
});

test('cookiePairsFromSetCookie rewrites only the host attributes, keeps httponly', () => {
  const upstream = 'session_token=tok; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=3600';
  const out = cookiePairsFromSetCookie(upstream);
  assert.equal(out.maxAge, '3600');
  assert.match(out.cookie, /session_token=tok/);
  assert.match(out.cookie, /httponly/i);
  assert.match(out.cookie, /path=\//i);
  assert.doesNotMatch(out.cookie, /domain=/i);
});

test('cookiePairsFromSetCookie surfaces the upstream Secure/SameSite attributes', () => {
  // The login route re-issues the cookie to the browser and must carry these through:
  // dropping Secure would let the session cookie travel over plaintext once edge TLS is
  // live (SECURITY §2 cookie semantics; authService sets Secure from COOKIE_SECURE).
  const out = cookiePairsFromSetCookie('session_token=tok; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=3600');
  assert.equal(out.secure, true);
  assert.equal(out.sameSite, 'Strict');
  const plain = cookiePairsFromSetCookie('session_token=tok; Path=/; HttpOnly; SameSite=Lax; Max-Age=60');
  assert.equal(plain.secure, false);
  assert.equal(plain.sameSite, 'Lax');
});

test('askResponseWhitelist passes only the documented fields', () => {
  const upstream = {
    sql: 'SELECT 1', rows: [{ a: 1 }], row_count: 1, role: 'nmc_officer',
    schema_chunks_used: 5, model: 'qwen3:1.7b', secret_internal: 'x',
  };
  assert.deepEqual(askResponseWhitelist(upstream), {
    sql: 'SELECT 1', rows: [{ a: 1 }], row_count: 1, role: 'nmc_officer',
  });
});

test('logout relays the session to authService /logout and clears the cookie', async () => {
  // The dashboard's Sign out calls DELETE /api/login; without this the handler did not
  // exist, Next answered 405, and the session was never revoked (the cookie stayed valid).
  const calls = [];
  const out = await logout('other=1; session_token=tok', { AUTH_URL: 'http://auth:4000' }, async (url, opts) => {
    calls.push({ url, opts });
    return { status: 200 };
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://auth:4000/logout');
  assert.equal(calls[0].opts.method, 'POST');
  assert.equal(calls[0].opts.headers.authorization, 'Bearer tok');
  assert.equal(out.cookie.value, '');
  assert.equal(out.cookie.maxAge, 0);
  assert.ok(out.cookie.httpOnly);
});

test('logout without a session clears the cookie and does not call upstream', async () => {
  let called = false;
  const out = await logout('', {}, async () => { called = true; });
  assert.equal(called, false);
  assert.equal(out.cookie.value, '');
  assert.equal(out.cookie.maxAge, 0);
});

test('upstreamFromEnv honours env overrides and defaults to the frozen registry', () => {
  const def = upstreamFromEnv({});
  assert.match(def.auth, /auth-service\.nagar-app\.svc\.cluster\.local:4000$/);
  assert.match(def.slm, /slm-service\.nagar-app\.svc\.cluster\.local:4004$/);
  const over = upstreamFromEnv({ AUTH_URL: 'http://a:1', SLM_URL: 'http://s:2' });
  assert.equal(over.auth, 'http://a:1');
  assert.equal(over.slm, 'http://s:2');
});
