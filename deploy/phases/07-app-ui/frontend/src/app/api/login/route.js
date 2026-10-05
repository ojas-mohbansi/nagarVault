// Frontend BFF route handlers — Phase 7g (Node runtime; pure logic in src/lib/bff.js
// is covered by the hermetic suite; these handlers wire it to Next's Request/Response).
import { NextResponse } from 'next/server';
import { bearerFromCookie, cookiePairsFromSetCookie, loginBody, logout, upstreamFromEnv } from '../../../lib/bff.js';

export const dynamic = 'force-dynamic';

export async function POST(request) {
  const upstream = upstreamFromEnv(process.env);
  let raw;
  try {
    raw = await request.json();
  } catch {
    return NextResponse.json({ detail: 'invalid JSON body' }, { status: 400 });
  }
  let body;
  try {
    body = loginBody(raw);
  } catch (e) {
    return NextResponse.json({ detail: e.message }, { status: 400 });
  }
  const r = await fetch(`${upstream.auth}/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await r.json().catch(() => ({}));
  const response = NextResponse.json(payload, { status: r.status });
  const setCookie = r.headers.get('set-cookie');
  if (setCookie) {
    const { cookie, maxAge, secure, sameSite } = cookiePairsFromSetCookie(setCookie);
    if (cookie) {
      response.cookies.set({
        name: 'session_token',
        value: cookie.split(';')[0].split('=').slice(1).join('='),
        httpOnly: true,
        // Relay upstream's attributes: dropping Secure here would let the session cookie
        // travel over plaintext once edge TLS is live (SECURITY §2).
        sameSite: sameSite ? sameSite.toLowerCase() : 'lax',
        secure,
        path: '/',
        maxAge: maxAge ? Number(maxAge) : undefined,
      });
    }
  }
  return response;
}

export async function DELETE(request) {
  // Sign out: revoke the session at authService and clear the browser cookie (the dashboard
  // calls DELETE /api/login). Without this handler Next answered 405 and the session stayed
  // valid — Sign out only navigated away.
  const { body, cookie } = await logout(request.headers.get('cookie') || '', process.env);
  const response = NextResponse.json(body);
  response.cookies.set(cookie);
  return response;
}

export async function GET(request) {
  // Shared helper for whoami-style relays: cookie -> Bearer.
  const bearer = bearerFromCookie(request.headers.get('cookie') || '');
  if (!bearer) return NextResponse.json({ detail: 'missing session' }, { status: 401 });
  const upstream = upstreamFromEnv(process.env);
  const r = await fetch(`${upstream.auth}/whoami`, {
    headers: { authorization: `Bearer ${bearer}` },
  });
  const payload = await r.json().catch(() => ({}));
  return NextResponse.json(payload, { status: r.status });
}
