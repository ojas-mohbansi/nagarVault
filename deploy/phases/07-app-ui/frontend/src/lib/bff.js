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
  if (!setCookie) return { cookie: null, maxAge: null, secure: false, sameSite: null };
  const parts = setCookie.split(';').map((p) => p.trim());
  const [nameValue, ...attrs] = parts;
  const maxAge = attrs.find((a) => /^max-age=/i.test(a));
  // SameSite/Secure are relayed as upstream sent them (COOKIE_SECURE flips with Phase 8
  // edge TLS). They are reported separately so the login route re-issues the browser
  // cookie with the same attributes rather than silently dropping Secure.
  const sameSite = attrs.find((a) => /^samesite=/i.test(a));
  const secure = attrs.some((a) => /^secure$/i.test(a));
  // Re-emit the cookie host-only (no Domain), httponly, path=/.
  const keep = attrs.filter((a) => /^samesite=/i.test(a) || /^secure$/i.test(a));
  const cookie = [nameValue, 'Path=/', 'HttpOnly', ...keep].join('; ');
  return {
    cookie,
    maxAge: maxAge ? maxAge.split('=')[1] : null,
    secure,
    sameSite: sameSite ? sameSite.split('=')[1] : null,
  };
}

const ASK_FIELDS = ['sql', 'rows', 'row_count', 'role'];

export function askResponseWhitelist(payload) {
  const out = {};
  for (const f of ASK_FIELDS) if (payload && payload[f] !== undefined) out[f] = payload[f];
  return out;
}

// Logout relay (the dashboard's Sign out → DELETE /api/login). Revocation is recorded in
// authService (POST /logout, cookie relayed as Bearer) and the host-only session cookie is
// cleared. A failed upstream call still clears the local cookie — the officer must always be
// able to sign out of this browser; the server-side revocation is retried by the next logout.
export async function logout(cookieHeader, env, fetchImpl = fetch) {
  const bearer = bearerFromCookie(cookieHeader || '');
  const upstream = upstreamFromEnv(env);
  if (bearer) {
    try {
      await fetchImpl(`${upstream.auth}/logout`, {
        method: 'POST',
        headers: { authorization: `Bearer ${bearer}` },
      });
    } catch {
      // best-effort: the local cookie is cleared regardless
    }
  }
  return {
    body: { status: 'ok' },
    cookie: { name: COOKIE_NAME, value: '', maxAge: 0, path: '/', httpOnly: true, sameSite: 'lax' },
  };
}

export function upstreamFromEnv(env) {
  return {
    auth: env.AUTH_URL || 'http://auth-service.nagar-app.svc.cluster.local:4000',
    slm: env.SLM_URL || 'http://slm-service.nagar-app.svc.cluster.local:4004',
  };
}
