// Frontend BFF route: GET /api/whoami -> authService GET /whoami with the session
// cookie relayed as Bearer (ADR-023: the browser only ever talks to :3001).
import { NextResponse } from 'next/server';
import { bearerFromCookie, upstreamFromEnv } from '../../../lib/bff.js';

export const dynamic = 'force-dynamic';

export async function GET(request) {
  const bearer = bearerFromCookie(request.headers.get('cookie') || '');
  if (!bearer) return NextResponse.json({ detail: 'missing session' }, { status: 401 });
  const upstream = upstreamFromEnv(process.env);
  const r = await fetch(`${upstream.auth}/whoami`, {
    headers: { authorization: `Bearer ${bearer}` },
  });
  const payload = await r.json().catch(() => ({}));
  return NextResponse.json(payload, { status: r.status });
}
