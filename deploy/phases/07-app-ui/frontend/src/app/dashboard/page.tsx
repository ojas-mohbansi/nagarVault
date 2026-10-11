"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PlayIcon, LogoutIcon, CodeIcon, CheckIcon, AlertIcon } from "../../components/icons";

type Whoami = { sub: string; role: string; exp: number };

type AskResult = {
  sql: string;
  rows: Record<string, unknown>[];
  row_count: number;
  role: string;
};

// /api/ask (src/app/api/ask/route.js) forwards slmService's own payload. On failure the
// BFF passes `detail` through untouched; queryService gate verdicts arrive as a STRUCTURED
// object ({reason, verdict}) rather than a string. Rendering that object directly would make
// React throw and blank the console, so it must be flattened to text inside the alert —
// otherwise the officer never sees why their read was blocked (WCAG 3.3.1 error
// identification, and the console's whole point is explaining refusals).
function errorText(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") {
    const d = detail as { reason?: string; verdict?: string; detail?: string };
    const reason = d.reason ?? d.detail;
    if (reason) return [reason, d.verdict].filter(Boolean).join(" — ");
    return JSON.stringify(detail);
  }
  if (status === 401) return "Session expired — sign in again.";
  return `Query failed (HTTP ${status}).`;
}

// Presets are plain-language questions, not SQL. They exist because officers repeat a small
// number of reads during a shift and typing them out on a dock terminal is the slow path.
const PRESETS = [
  "Uninspected water distribution valves in Ward 7",
  "Open complaints grouped by ward, highest first",
  "Assets flagged during monsoon triage",
];

const DEFAULT_QUESTION =
  "Show uninspected water distribution valves in Ward 7 reported during monsoon triage";

// The console renders at most this many rows. The full row_count is reported honestly
// beside it; this is a display cap, not a result cap.
const MAX_ROWS = 50;

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Whoami | null>(null);
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);

  useEffect(() => {
    fetch("/api/whoami")
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((j: Whoami) => setMe(j))
      .catch(() => router.push("/login"));
  }, [router]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || asking) return;
    setError("");
    setResult(null);
    setAsking(true);
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        const body = j as AskResult;
        setResult({
          sql: body.sql ?? "",
          rows: Array.isArray(body.rows) ? body.rows : [],
          row_count: typeof body.row_count === "number" ? body.row_count : body.rows?.length ?? 0,
          role: body.role ?? "",
        });
      } else if (r.status === 401) {
        router.push("/login");
      } else {
        setError(errorText((j as { detail?: unknown }).detail, r.status));
      }
    } catch {
      setError("slmService unreachable — the console could not reach the query path.");
    } finally {
      setAsking(false);
    }
  }

  async function signOut() {
    // DELETE /api/login revokes the session at authService AND clears the host-only cookie
    // (src/app/api/login/route.js). A failed upstream revocation still clears locally, so the
    // officer is never trapped in a session they cannot end.
    await fetch("/api/login", { method: "DELETE" }).catch(() => {});
    router.push("/login");
    router.refresh();
  }

  const shown = result ? result.rows.slice(0, MAX_ROWS) : [];
  // Columns come from the returned rows themselves — the console never hardcodes a schema,
  // because the SLM compiles whatever projection the question implies.
  const columns = useMemo(() => (shown.length > 0 ? Object.keys(shown[0]) : []), [shown]);

  const sessionEnds = me?.exp
    ? new Date(me.exp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <div className="container">
      {/* Identity — who the BFF says you are, and a way out of the session. */}
      <section className="panel identity-strip" aria-label="Session identity" style={{ marginBottom: "1.2rem" }}>
        <span className="term">PRINCIPAL</span>
        <strong className="ok">{me?.sub ?? "…"}</strong>
        <span className="term muted" style={{ marginLeft: "0.5rem" }}>
          {me?.role ?? ""}
        </span>
        {sessionEnds && (
          <span className="term muted" style={{ marginLeft: "1rem" }}>
            SESSION EXPIRES <strong style={{ color: "var(--text)" }}>{sessionEnds}</strong>
          </span>
        )}
        <span style={{ marginLeft: "auto" }}>
          <button className="btn btn-ghost" type="button" onClick={signOut}>
            <LogoutIcon width={14} height={14} />
            Sign out
          </button>
        </span>
      </section>

      {/* Natural-language query compiler. */}
      <section className="panel" aria-labelledby="compiler-title" style={{ marginBottom: "1.2rem" }}>
        <div className="panel-head">
          <CodeIcon width={16} height={16} />
          <h1 id="compiler-title" className="section-title" style={{ margin: 0 }}>
            Ask the warehouse
          </h1>
          <span className="section-sub" style={{ marginLeft: "0.5rem" }}>
            local model · validated SQL · read-only
          </span>
        </div>

        <div className="panel-body">
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.8rem" }}>
            <span className="term muted" style={{ fontSize: "0.68rem" }}>
              PRESETS:
            </span>
            {PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                className="btn btn-secondary"
                style={{ fontSize: "0.75rem", padding: "0.3rem 0.6rem" }}
                onClick={() => setQuestion(p)}
              >
                {p}
              </button>
            ))}
          </div>

          <form className="dash-form" onSubmit={ask}>
            <label htmlFor="ask-question" className="section-label">
              Question
            </label>
            <textarea
              id="ask-question"
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. How many open complaints are there in each ward?"
              maxLength={2000}
              required
              aria-describedby="ask-hint"
              disabled={asking}
            />
            <p id="ask-hint" className="field-hint">
              Reads only. The warehouse answers counts, totals, and breakdowns — it cannot be
              asked to change data.
            </p>

            <div className="btn-row">
              <button type="submit" className="btn btn-primary" disabled={asking || !question.trim()}>
                {asking ? (
                  <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
                    <span className="spin" aria-hidden="true">
                      ⌁
                    </span>
                    Compiling…
                  </span>
                ) : (
                  <span style={{ display: "inline-flex", gap: "0.35rem", alignItems: "center" }}>
                    <PlayIcon width={16} height={16} />
                    Run query
                  </span>
                )}
              </button>
            </div>
          </form>

          {error && (
            <div className="form-error" style={{ marginTop: "0.75rem" }} role="alert">
              <div className="alert error">
                <AlertIcon width={16} height={16} className="ico" />
                <span>{error}</span>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Compiled readout — the SQL the model produced, verbatim, so the officer can audit it. */}
      {result?.sql && (
        <section className="panel" aria-labelledby="readout-title" style={{ marginBottom: "1.2rem" }}>
          <div className="panel-head">
            <span className="term" id="readout-title">
              COMPILED SQL
            </span>
            <span className="section-sub" style={{ marginLeft: "0.5rem" }}>
              as executed
            </span>
            <span style={{ marginLeft: "auto" }}>
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => {
                  navigator.clipboard?.writeText(result.sql).catch(() => {});
                }}
              >
                Copy
              </button>
            </span>
          </div>
          <div className="panel-body">
            <pre className="readout">{result.sql}</pre>
          </div>
        </section>
      )}

      {/* Results. */}
      <section className="panel" aria-labelledby="ledger-title">
        <div className="panel-head">
          <h2 id="ledger-title" className="section-title" style={{ margin: 0 }}>
            Results
          </h2>
          <span className="section-sub" style={{ marginLeft: "0.5rem" }}>
            {result
              ? `${result.row_count} row${result.row_count === 1 ? "" : "s"}`
              : "no query run yet"}
          </span>
        </div>

        <div className="panel-body" aria-live="polite">
          {result && shown.length > 0 ? (
            <>
              <div style={{ overflowX: "auto" }}>
                <table className="ledger">
                  <caption className="sr-only">
                    Query results: {result.row_count} rows, {columns.length} columns
                  </caption>
                  <thead>
                    <tr>
                      {columns.map((c) => (
                        <th key={c} scope="col">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((row, i) => (
                      <tr key={i}>
                        {columns.map((c) => (
                          <td key={c}>
                            <span className="col-id">{row[c] === null || row[c] === undefined ? "—" : String(row[c])}</span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {result.row_count > shown.length && (
                <p className="muted" style={{ fontSize: "0.78rem", margin: "0.6rem 0 0" }}>
                  Showing the first {shown.length} of {result.row_count} rows. Narrow the question
                  to see the rest.
                </p>
              )}
            </>
          ) : result ? (
            <p className="empty-state">The query ran successfully and matched no rows.</p>
          ) : (
            <p className="empty-state">Ask a question above to populate the ledger.</p>
          )}
        </div>
      </section>

      <footer className="footer-bar" style={{ marginTop: "1.5rem" }}>
        <span className="term" style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
          <CheckIcon width={14} height={14} />
          Read-only session · no writes are possible from this console
        </span>
      </footer>
    </div>
  );
}
