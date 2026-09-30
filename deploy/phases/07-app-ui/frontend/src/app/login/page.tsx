"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const r = await fetch("/api/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.status === "ok") {
        router.push("/dashboard");
        return;
      }
      setError(j.detail ?? `login failed (${r.status})`);
    } catch {
      setError("auth service unreachable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>NagarVault — Officer Console</h1>
      <p className="muted">Sign in with your municipal account.</p>
      <form onSubmit={submit}>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      {error && <p className="err">{error}</p>}
    </main>
  );
}
