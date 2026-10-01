// Public presigned-URL adapter — Phase 7e (Phase-8 charter closure; ADR-025).
//
// The API mints presigned PUTs for the BROWSER, which reaches MinIO only through the
// Traefik edge: the frozen `/minio` route (ADR-024 §5/§6) strips the prefix before the
// request reaches MinIO. Two facts drive this adapter:
//
//   1. A SigV4 presigned URL is bound to its signed HOST, so the signer (not the client)
//      must target the public edge origin — rewriting only the returned URL's host would
//      break the signature. runtime.js therefore signs with a second S3 client whose
//      endpoint is PRESIGN_PUBLIC_URL.
//   2. The route prefix is signature-NEUTRAL: MinIO verifies the request it actually
//      receives, and after the edge strip that is exactly the MinIO-native path the
//      signature was computed over. So the presented path simply gains the prefix.
//
// When PRESIGN_PUBLIC_URL is unset the signed URL is returned untouched — in-cluster
// consumers keep the legacy MINIO_URL behavior.
export function toPublicPresignedUrl(signedUrl, publicUrl, routePrefix = '/minio') {
  if (!publicUrl) return signedUrl;
  const base = new URL(publicUrl);
  const u = new URL(signedUrl);
  u.protocol = base.protocol;
  u.hostname = base.hostname;
  // NB: assign the port explicitly — setting only `host`/`hostname` leaves a previously
  // parsed port (e.g. MINIO_URL's :9000) in place on this runtime.
  u.port = base.port;
  u.pathname = `${String(routePrefix).replace(/\/+$/, '')}${u.pathname}`;
  return u.toString();
}
