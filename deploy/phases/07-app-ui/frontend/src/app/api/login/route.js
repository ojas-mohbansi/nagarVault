// Frontend BFF route handlers — Phase 7g (Node runtime; pure logic in src/lib/bff.js
// is covered by the hermetic suite; these handlers wire it to Next's Request/Response).
import { NextResponse } from 'next/server';
import { bearerFromCookie, cookiePairsFromSetCookie, loginBody, upstreamFromEnv } from '../../../lib/bff.js';

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
    const { cookie, maxAge } = cookiePairsFromSetCookie(setCookie);
    if (cookie) {
      response.cookies.set({
        name: 'session_token',
        value: cookie.split(';')[0].split('=').slice(1).join('='),
        httpOnly: true,
        sameSite: 'lax',
        path: '/',
        maxAge: maxAge ? Number(maxAge) : undefined,
      });
    }
  }
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
