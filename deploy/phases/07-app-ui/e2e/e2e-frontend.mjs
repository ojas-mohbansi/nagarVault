// Phase 7g — frontend E2E (run INSIDE a frontend pod, §12.26: the BFF is the subject).
//   cat secrets | kubectl exec -i <frontend-pod> -- sh -c 'read -r E2E_PW_A; read -r E2E_PW_O; export E2E_PW_A E2E_PW_O; node /tmp/e2e7g.mjs'
// Passwords come from real minted fixture users (e2e-7g-001/e2e-7g-002) via stdin only.
// Covers, through the BFF on localhost:3001:
//   1. officer /api/login -> 200 {status:ok} + httponly Set-Cookie relayed
//   2. officer /api/whoami (cookie relayed as Bearer) -> 200 {sub, role}
//   3. officer /api/ask -> 200 {sql, rows, row_count, role} — real bge-m3 -> qdrant ->
//      qwen3 -> queryService RBAC (officer's own token forwarded)
//   4. admin /api/ask -> 403 with the structured table-rbac verdict pass-through
//      (SECURITY §3: admin has NO warehouse tables — proven through the UI)
//   5. /api/ask without cookie -> 401; bad credentials -> 401
//   6. legacy login fields (user_id) are dropped by the BFF whitelist -> still 200
const BASE = 'http://localhost:3001';

const out = {};
const jar = {};

async function call(path, { method = 'GET', body, cookieName } = {}) {
  const headers = {};
  if (body !== undefined) headers['content-type'] = 'application/json';
  if (cookieName && jar[cookieName]) headers.cookie = `session_token=${jar[cookieName]}`;
  const r = await fetch(BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const setCookie = r.headers.get('set-cookie');
  let payload;
  try { payload = await r.json(); } catch { payload = await r.text(); }
  return { status: r.status, payload, setCookie };
}

// 1. officer login through the BFF
const off = await call('/api/login', {
  method: 'POST',
  body: { username: 'off7g', password: process.env.E2E_PW_O, user_id: 'legacy-noise' },
});
out.officerLogin = { status: off.status, body: off.payload, cookieRelayed: /httponly/i.test(off.setCookie || '') };
if (off.setCookie) jar.off = off.setCookie.split(';')[0].split('=')[1];

// 2. officer identity through the BFF
const who = await call('/api/whoami', { cookieName: 'off' });
out.officerWhoami = { status: who.status, body: who.payload };

// 3. officer ask — real NL -> SQL -> rows with the officer's own RBAC
const askOff = await call('/api/ask', {
  method: 'POST', cookieName: 'off',
  body: { question: 'How many complaints are in the warehouse in total?' },
});
out.officerAsk = {
  status: askOff.status,
  keys: Object.keys(askOff.payload || {}).sort(),
  row_count: askOff.payload?.row_count,
  role: askOff.payload?.role,
  sql: askOff.payload?.sql,
};

// 4. admin ask — the RBAC wall seen through the UI
const adm = await call('/api/login', { method: 'POST', body: { username: 'adm7g', password: process.env.E2E_PW_A } });
if (adm.setCookie) jar.adm = adm.setCookie.split(';')[0].split('=')[1];
out.adminLogin = { status: adm.status };
const askAdm = await call('/api/ask', {
  method: 'POST', cookieName: 'adm',
  body: { question: 'List every complaint record with all columns.' },
});
out.adminAskBlocked = { status: askAdm.status, detail: askAdm.payload?.detail };

// 5. negative authz
out.askNoCookie = (await call('/api/ask', { method: 'POST', body: { question: 'x' } })).status;
out.badCreds = (await call('/api/login', { method: 'POST', body: { username: 'off7g', password: 'wrong' } })).status;

console.log('E2E-RESULT ' + JSON.stringify(out, null, 1));
