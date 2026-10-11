import type { Metadata, Viewport } from "next";
import "./globals.css";

/**
 * Root layout — Phase 7g officer console shell.
 *
 * The schema refactor changed how a request is interpreted (synthetic principals and column
 * ACLs are evaluated server-side), not how the console is bootstrapped. This layout stays a
 * static chrome layer: it declares a11y-relevant page metadata, registers the PWA manifest and
 * SVG favicon (no webfonts — air-gap survivability), and renders the fixed topbar/nav chrome that
 * every officer page inherits. Icons are inline SVG defined locally below, not components pulled
 * out of a shared module, so the shell has no runtime dependency on any other tree.
 */

export const metadata: Metadata = {
  title: "NagarVault — Officer Console",
  description: "Air-gapped municipal intelligence console",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "NagarVault",
  },
  // A11y-relevant metadata: the console is used by officers under time pressure, and the
  // recurrent-blindness / screen-reader population is not negligible in civic roles, so the
  // language and generator hint are declared explicitly rather than inferred.
  generator: "NagarVault",
};

// colorScheme/themeColor belong to the viewport export in the App Router — declaring them in
// `metadata` is ignored (and warns) since Next 14. Keeping the dark scheme here means the
// browser paints form controls and scrollbars dark before first paint, which matters on a
// terminal that is always dark and would otherwise flash white.
export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#070b0a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#070b0a" />
        <meta name="color-scheme" content="dark" />
        {/* No webfonts. SVG favicon is inline-declared so the console never makes an outbound
            icon request — that keeps the page usable on an air-gapped host and avoids a flash of the
            wrong icon during the first paint. */}
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
      </head>
      <body>
        <div className="app-shell" role="application" aria-label="NagarVault officer console">
          <header className="topbar" role="banner">
            <a className="brand" href="/dashboard" aria-label="NagarVault — Officer Console">
              <ShieldIcon size={18} />
              <span>
                NagarVault
                <small>Registry Intelligence</small>
              </span>
            </a>

            <span className="status term" aria-label="Operational node online, air-gapped security zone, 1.8ms round trip">
              <span className="dot" aria-hidden="true" />
              <span>NODE: k3d.agar.internal:36000</span>
              <span aria-hidden="true">|</span>
              <span>TOPOLOGY: AIR-GAPPED SEC-ZONE</span>
              <span aria-hidden="true">|</span>
              <span>RTT: 1.8ms</span>
            </span>
          </header>

          <nav className="nav" aria-label="Primary">
            <a href="/dashboard" className="seg active" aria-current="page">
              <ListIcon size={16} />
              Ledger Records
            </a>
            <span className="seg" aria-hidden="true" style={{ cursor: "default", pointerEvents: "none" }}>
              <CodeIcon size={16} />
              SQL
            </span>
            <span className="seg" aria-hidden="true" style={{ cursor: "default", pointerEvents: "none" }}>
              <ShieldIcon size={16} />
              Field Inspection
            </span>
            <span className="seg" aria-hidden="true" style={{ cursor: "default", pointerEvents: "none" }}>
              <ClipboardIcon size={16} />
              Audit Trail
            </span>
            <span className="seg" aria-hidden="true" style={{ cursor: "default", pointerEvents: "none" }}>
              <WavesIcon size={16} />
              Telemetry
            </span>

            <span style={{ flex: 1 }} aria-hidden="true" />

            <span className="term" style={{ color: "var(--muted)", fontSize: "0.72rem" }}>
              Ward: <strong style={{ color: "var(--text)" }}>WARD-07 (North)</strong>
            </span>
            <a href="/dashboard" className="btn btn-ghost" aria-label="Export TSV" tabIndex={-1}>
              Export TSV
            </a>
          </nav>

          <main className="main" id="main-content" tabIndex={-1}>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

// Local icons take the same optional `size` shorthand as src/components/icons.tsx so the
// shell chrome and the page bodies share one calling convention.
type IconProps = React.SVGProps<SVGSVGElement> & { size?: number };

function ListIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <line x1={8} y1={6} x2={21} y2={6} />
      <line x1={8} y1={12} x2={21} y2={12} />
      <line x1={8} y1={18} x2={21} y2={18} />
      <line x1={3} y1={6} x2={3.01} y2={6} />
      <line x1={3} y1={12} x2={3.01} y2={12} />
      <line x1={3} y1={18} x2={3.01} y2={18} />
    </svg>
  );
}

function CodeIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <polyline points="16,18 22,12 16,6" />
      <polyline points="8,6 2,12 8,18" />
    </svg>
  );
}

/**********************************************************************
 * Local inline SVG icon primitives — deliberately defined in this file, not imported
 * from a shared component tree. The console is air-gapped: every icon must be present at
 * build time with zero network dependency, and pulling icon components out of a separate
 * module would create an implicit runtime coupling and a future class of refactors that
 * forget the icon is part of the frozen shell. Each icon is 16–20px, stroke-based, and
 * uses currentColor so the surrounding text color governs it. The type annotation is
 * React.SVGProps<SVGSVGElement> so any className/aria/width/height still works.
 **********************************************************************/
function ShieldIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
    </svg>
  );
}

function EyesIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx={12} cy={12} r={2.5} />
    </svg>
  );
}

function EyesOffIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
      <path d="M10.9 16.56a6 6 0 0 0 4.56-2.16" />
      <line x1={3} y1={21} x2={21} y2={3} />
    </svg>
  );
}

function LogoutIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16,17 21,12 16,7" />
      <line x1={21} y1={12} x2={9} y2={12} />
    </svg>
  );
}

function CheckIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <polyline points="20,6 9,17 4,12" />
    </svg>
  );
}

function SearchIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <circle cx={11} cy={11} r={7} />
      <line x1={21} y1={21} x2={16} y2={16} />
    </svg>
  );
}

function TerminalIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <polyline points="4,17 10,11 4,5" />
      <line x1={12} y1={19} x2={20} y2={19} />
    </svg>
  );
}

function ClipboardIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M16 4h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h4" />
      <rect x={8} y={2} width={8} height={4} rx={1} />
    </svg>
  );
}

function WavesIcon({ size = 16, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M2 12c1.5-2 3-2 4.5 0" />
      <path d="M7.5 12c1.5-2 3-2 4.5 0" />
      <path d="M13 12c1.5-2 3-2 4.5 0" />
      <path d="M18.5 12c1.5-2 3-2 4.5 0" />
    </svg>
  );
}
