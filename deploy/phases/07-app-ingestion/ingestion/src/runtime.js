// Production wiring for the ingestion backend: binds the injectable seams to the real
// clients (MinIO via AWS SDK S3 presigner, Redis via ioredis, Kafka via kafkajs) and
// starts the HTTP server. Tests replace these seams in-memory.
import http from 'node:http';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import Redis from 'ioredis';
import { Kafka } from 'kafkajs';
import { buildApp } from './app.js';
import { toPublicPresignedUrl } from './presign-url.js';

const MEDIA_BUCKET = process.env.MEDIA_BUCKET || 'raw-media';
const credentials = {
  accessKeyId: process.env.MINIO_ACCESS_KEY,
  secretAccessKey: process.env.MINIO_SECRET_KEY,
};
const s3 = new S3Client({
  endpoint: process.env.MINIO_URL || 'http://minio.nagar-platform.svc.cluster.local:9000',
  region: 'us-east-1',
  forcePathStyle: true,
  credentials,
});

// Browser-facing presigner (ADR-025): when PRESIGN_PUBLIC_URL is set, presigning is done
// against the public edge origin so the SigV4 host matches what MinIO sees through the
// edge, and the returned URL gains the frozen `/minio` route prefix. All read paths
// (statObject, health) and the unset default keep using the in-cluster MINIO_URL client.
const PRESIGN_PUBLIC_URL = process.env.PRESIGN_PUBLIC_URL || '';
const PRESIGN_ROUTE_PREFIX = process.env.PRESIGN_ROUTE_PREFIX || '/minio';
const s3Public = PRESIGN_PUBLIC_URL
  ? new S3Client({ endpoint: PRESIGN_PUBLIC_URL, region: 'us-east-1', forcePathStyle: true, credentials })
  : null;

const redis = new Redis(process.env.REDIS_URL || 'redis://redis.nagar-platform.svc.cluster.local:6379', {
  maxRetriesPerRequest: 2,
  lazyConnect: false,
});

const kafka = new Kafka({ clientId: 'ingestion', brokers: [process.env.KAFKA_BOOTSTRAP || 'nagar-kafka-bootstrap.nagar-platform.svc.cluster.local:29092'] });
const producer = kafka.producer();

globalThis.__ingestion = {
  store: {}, // unused in production (the seams below hit the real services)
  published: [],
  async presignUrls({ bucket, objectKey, contentType }) {
    const cmd = new PutObjectCommand({ Bucket: bucket, Key: objectKey, ContentType: contentType });
    const url = await getSignedUrl(s3Public || s3, cmd, { expiresIn: 300 }); // §3.2: 5-minute PUT URLs
    return toPublicPresignedUrl(url, PRESIGN_PUBLIC_URL, PRESIGN_ROUTE_PREFIX);
  },
  async statObject({ bucket, objectKey }) {
    const { HeadObjectCommand } = await import('@aws-sdk/client-s3');
    const out = await s3.send(new HeadObjectCommand({ Bucket: bucket, Key: objectKey }));
    return { size: out.ContentLength, etag: out.ETag };
  },
  async redisSet(key, value, ttlSeconds) { await redis.set(key, value, 'EX', ttlSeconds); },
  async redisGet(key) { return redis.get(key); },
  async redisExpire(key, ttlSeconds) { await redis.expire(key, ttlSeconds); },
  async kafkaSend(topic, key, value) { await producer.send({ topic, messages: [{ key: Buffer.from(key), value: Buffer.from(value) }] }); },
  // NB: MinIO's bare base URL answers 403 (S3 auth); the health gate must use the
  // /minio/health/live path in BOTH branches, not just the env-less fallback (G7e.2).
  async minioOk() {
    const base = process.env.MINIO_URL || 'http://minio.nagar-platform.svc.cluster.local:9000';
    return (await fetch(`${base}/minio/health/live`)).ok;
  },
  async kafkaOk() {
    const admin = kafka.admin();
    try { await admin.connect(); await admin.fetchTopicMetadata({ topics: ['nmc.complaints.raw.restricted.v1'] }); return true; }
    catch { return false; } finally { await admin.disconnect().catch(() => {}); }
  },
};

const app = buildApp();
const server = http.createServer(app);
// NB: must NOT be named INGESTION_PORT — the k8s Service named `ingestion` makes the
// kubelet inject INGESTION_PORT=tcp://<clusterip>:3000 (service-link env), and parseInt
// of that is NaN (ERR_SOCKET_BAD_PORT crash, G7e.1). See OPERATIONS §12.28.
const port = parseInt(process.env.INGESTION_HTTP_PORT || '3000', 10);

async function main() {
  await producer.connect();
  server.listen(port, '0.0.0.0', () => console.log(`ingestion listening on ${port}`));
}

const shutdown = async () => {
  server.close();
  await producer.disconnect().catch(() => {});
  redis.disconnect();
  process.exit(0);
};
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

main().catch((e) => { console.error('fatal:', e); process.exit(1); });
