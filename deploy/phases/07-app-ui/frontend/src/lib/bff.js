// frontend BFF pure logic — Phase 7g.
//
// The browser talks ONLY to this service (:3001, CONVENTIONS §4 "public edge" port).
// The BFF forwards to authService (:4000) and slmService (:4004) with the session
// cookie relayed as `Bearer <token>` — the UI holds zero secrets and the token never
// enters browser JS (SECURITY §6.2 keeps its secret table unchanged; §2 cookie
// semantics preserved: host-only, httponly, path=/).
export const COOKIE_NAME = 'session_token';

export function bearerFromCookie(cookieHeader) {
  if (!cookieHeader) return null;
  for (const part of String(cookieHeader).split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (name === COOKIE_NAME && value) return value;
  }
  return null;
}

export function loginBody(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('invalid login body');
  const { username, password } = raw;
  if (typeof username !== 'string' || !username) throw new Error('username required');
  if (typeof password !== 'string' || !password) throw new Error('password required');
  // The current Credentials contract is exactly {username, password}; the legacy
  // `user_id` field does not exist anymore and must never be forwarded.
  return { username, password };
}

export function cookiePairsFromSetCookie(setCookie) {
  if (!setCookie) return { cookie: null, maxAge: null };
  const parts = setCookie.split(';').map((p) => p.trim());
  const [nameValue, ...attrs] = parts;
  const maxAge = attrs.find((a) => /^max-age=/i.test(a));
  // Re-emit the cookie host-only (no Domain), httponly, path=/ — SameSite/Secure stay
  // as upstream sent them (COOKIE_SECURE flips with Phase 8 edge TLS).
  const keep = attrs.filter((a) => /^samesite=/i.test(a) || /^secure$/i.test(a));
  const cookie = [nameValue, 'Path=/', 'HttpOnly', ...keep].join('; ');
  return { cookie, maxAge: maxAge ? maxAge.split('=')[1] : null };
}

const ASK_FIELDS = ['sql', 'rows', 'row_count', 'role'];

export function askResponseWhitelist(payload) {
  const out = {};
  for (const f of ASK_FIELDS) if (payload && payload[f] !== undefined) out[f] = payload[f];
  return out;
}

export function upstreamFromEnv(env) {
  return {
    auth: env.AUTH_URL || 'http://auth-service.nagar-app.svc.cluster.local:4000',
    slm: env.SLM_URL || 'http://slm-service.nagar-app.svc.cluster.local:4004',
  };
}
