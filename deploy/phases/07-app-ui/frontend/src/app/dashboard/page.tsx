"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type Whoami = { sub: string; role: string; exp: number };
type AskResult = { sql: string; rows: Record<string, unknown>[]; row_count: number; role: string };

// queryService gate verdicts arrive as a structured detail ({reason, verdict}) via the BFF.
// Render it as text: an object child would make React throw and unmount the page, so the
// error alert would never be announced (WCAG 3.3.1).
function errorText(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
    const d = detail as { reason?: string; verdict?: string; detail?: string };
    const reason = d.reason ?? d.detail;
    if (reason) return [reason, d.verdict].filter(Boolean).join(" ");
    return JSON.stringify(detail);
  }
  return `ask failed (${status})`;
}

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<Whoami | null>(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);

  useEffect(() => {
    fetch("/api/whoami")
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((j) => setMe(j))
      .catch(() => router.push("/login"));
  }, [router]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);
    setAsking(true);
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        setResult(j as AskResult);
      } else {
        setError(errorText(j.detail, r.status));
      }
    } catch {
      setError("slm service unreachable");
    } finally {
      setAsking(false);
    }
  }

  async function logout() {
    await fetch("/api/login", { method: "DELETE" }).catch(() => {});
    router.push("/login");
  }

  const columns = result && result.rows.length > 0 ? Object.keys(result.rows[0]) : [];

  return (
    <main>
      <h1>NagarVault — Dashboard</h1>
      {me && (
        <p className="muted">
          signed in as <span className="ok">{me.sub}</span> ({me.role})
        </p>
      )}
      <button onClick={logout} type="button">Sign out</button>

      <h2>Ask the warehouse</h2>
      <form onSubmit={ask}>
        <label className="field-label">
          Ask a question about the warehouse
          <textarea
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. How many open complaints are there in each ward?"
            maxLength={2000}
            required
            aria-describedby="ask-hint"
          />
        </label>
        <p id="ask-hint" className="muted">
          Tip: ask for counts, totals, or breakdowns — the warehouse only answers{
            " "}SQL SELECT questions.
        </p>
        <button disabled={asking}>{asking ? "Thinking…" : "Ask"}</button>
      </form>

      {error && (
        <p className="err" role="alert">
          Error: {error}
        </p>
      )}

      {result && (
        <section>
          <pre>{result.sql}</pre>
          {result.rows.length === 0 ? (
            <p className="muted">No results found</p>
          ) : (
            <table>
              <thead>
                <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {result.rows.slice(0, 100).map((row, i) => (
                  <tr key={i}>{columns.map((c) => <td key={c}>{String(row[c])}</td>)}</tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted">{result.row_count} row(s) · executed with role {result.role}</p>
        </section>
      )}
    </main>
  );
}
