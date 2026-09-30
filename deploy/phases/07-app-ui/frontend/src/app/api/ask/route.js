// Frontend BFF route: POST /api/ask -> slmService POST /ask with the session cookie
// relayed as Bearer; the response is whitelisted so model internals never reach the
// browser (ADR-023: server-side BFF, no browser-held tokens).
import { NextResponse } from 'next/server';
import { askResponseWhitelist, bearerFromCookie, upstreamFromEnv } from '../../../lib/bff.js';

export const dynamic = 'force-dynamic';

export async function POST(request) {
  const bearer = bearerFromCookie(request.headers.get('cookie') || '');
  if (!bearer) return NextResponse.json({ detail: 'missing session' }, { status: 401 });

  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: 'invalid JSON body' }, { status: 400 });
  }
  const question = typeof body?.question === 'string' ? body.question.trim() : '';
  if (!question || question.length > 2000) {
    return NextResponse.json({ detail: 'question must be 1..2000 chars' }, { status: 400 });
  }

  const upstream = upstreamFromEnv(process.env);
  const r = await fetch(`${upstream.slm}/ask`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${bearer}` },
    body: JSON.stringify({ question }),
  });
  const payload = await r.json().catch(() => ({ detail: 'upstream returned non-JSON' }));
  if (r.status !== 200) {
    return NextResponse.json(
      { detail: typeof payload?.detail === 'string' ? payload.detail : 'ask failed' },
      { status: r.status },
    );
  }
  return NextResponse.json(askResponseWhitelist(payload), { status: 200 });
}
