"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  LockIcon,
  EyeIcon,
  EyeOffIcon,
  AlertIcon,
} from "../../components/icons";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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
        router.refresh();
        return;
      }
      setError((j.detail as string | undefined) ?? `login failed (${r.status})`);
    } catch {
      setError("auth service unreachable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="card-head">
          <div className="auth-id">
            <LockIcon size={20} />
            <span>
              Classified Municipal Terminal
              <small>DOMAIN_UID</small>
            </span>
          </div>
        </div>

        <div className="card-body">
          <h1 id="login-title" style={{ margin: "0 0 0.25rem", fontSize: "1.15rem" }}>
            Officer Principal
          </h1>
          <p className="muted" style={{ fontSize: "0.8rem", margin: "0 0 1.2rem" }}>
            Sign in with your municipal account.
          </p>

          <form onSubmit={submit} noValidate>
            <div className="form-group">
              <label htmlFor="login-username">Identifier</label>
              <div className="auth-id" style={{ width: "100%", marginBottom: 0 }}>
                <input
                  id="login-username"
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="r.sharma@nagar.internal"
                  required
                  aria-describedby="username-hint"
                />
                <small style={{ width: "5rem", flex: "none", margin: 0, textAlign: "right" }}>
                  Tab -&gt;
                </small>
              </div>
              <p id="username-hint" className="field-hint">
                Primary directory handle registered in the National Capital municipal cluster.
              </p>
            </div>

            <div className="form-group">
              <label htmlFor="login-password">Passphrase or Hardware Token</label>
              <div style={{ position: "relative" }}>
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  aria-describedby="password-hint"
                  style={{ paddingRight: "2.6rem" }}
                />
                <button
                  type="button"
                  className="eye-toggle"
                  aria-label={showPassword ? "Hide passphrase" : "Show passphrase"}
                  onClick={() => setShowPassword((v) => !v)}
                  style={{ position: "absolute", right: "0.4rem", top: "50%", transform: "translateY(-50%)" }}
                >
                  {showPassword ? <EyeOffIcon size={18} /> : <EyeIcon size={18} />}
                </button>
              </div>
              <p id="password-hint" className="field-hint">
                Supports YubiKey 5 Series PIV or 24-character master passphrase.
              </p>
            </div>

            <button type="submit" className="btn btn-primary" disabled={busy} style={{ width: "100%", marginTop: "0.25rem" }}>
              {busy ? (
                <span className="term" style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
                  <span className="spin" aria-hidden="true">⌁</span>
                  Authorizing session…
                </span>
              ) : (
                <span className="term" style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
                  <LockIcon size={16} />
                  Authorize Session
                  <span aria-hidden="true" style={{ fontFamily: "inherit" }}>↵</span>
                </span>
              )}
            </button>
          </form>

          {error && (
            <div className="form-error" role="alert">
              <div className="alert error" style={{ display: "block" }}>
                <AlertIcon size={16} className="ico" />
                <span>{error}</span>
              </div>
            </div>
          )}
        </div>

        <div className="card-foot">
          <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
            <span className="dot" style={{ width: 7, height: 7, background: "var(--accent)", boxShadow: "0 0 0 2px rgba(52,211,153,0.18)" }} aria-hidden="true" />
            CERT: VALID (EXPIRES IN 284D)
          </span>
          <span aria-hidden="true" style={{ marginLeft: "auto", opacity: 0.6 }}>|</span>
          <a href="/dashboard" className="btn-ghost" style={{ color: "var(--accent)", textDecoration: "underline", background: "none", border: 0, cursor: "default" }} aria-disabled="true" tabIndex={-1}>
            Air-Gap Token Recovery
          </a>
        </div>
      </section>
    </div>
  );
}
