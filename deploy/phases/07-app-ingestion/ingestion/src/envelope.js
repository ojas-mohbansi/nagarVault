// Envelope + routing — the 7e producer side of the 7c wire contract.
//
// The envelope shape and the topic registry are copied verbatim from
// deploy/phases/07-app-worker/worker/enrich.py (TOPIC_TABLE / FIELD_MAPS) and
// docs/ARCHITECTURE.md §4.2 — the worker is the consumer of record; this module is
// the producer and must satisfy it exactly (cross-service tests pin this).
export const TOPIC_ROUTES = {
  complaints: 'nmc.complaints.raw.restricted.v1',
  traffic: 'traffic.events.raw.v1',
  water: 'water.sensors.raw.v1',
  health: 'health.camps.raw.v1',
  ev: 'ev.bus.telemetry.raw.v1',
};

// API-schema required fields per department (what /api/v1/events refuses before Kafka).
// The worker's own required fields are a subset (e.g. water also needs sensorId+parameter
// at the worker level; the API enforces them too so bad events never reach the topic).
export const API_REQUIRED = {
  complaints: ['description'],
  traffic: [],
  water: ['sensorId', 'parameter'],
  health: [],
  ev: ['busId'],
};

export const API_NUMERIC = {
  complaints: {},
  traffic: { vehicleCount: 'int', averageSpeed: 'float' },
  water: { value: 'float' },
  health: {},
  ev: { latitude: 'float', longitude: 'float', speedKph: 'float', stateOfCharge: 'float' },
};

export function routeFor(department) {
  const topic = TOPIC_ROUTES[department];
  if (!topic) throw new Error(`unknown department: ${department}`);
  return topic;
}

function coerce(department, payload) {
  const rules = API_NUMERIC[department] || {};
  const out = { ...payload };
  for (const [key, kind] of Object.entries(rules)) {
    if (out[key] === undefined || out[key] === null) continue;
    const n = kind === 'int' ? parseInt(out[key], 10) : parseFloat(out[key]);
    if (Number.isNaN(n)) throw new Error(`field ${key} must be a number`);
    out[key] = n;
  }
  return out;
}

export function buildEnvelope({ department, eventId, sourceSystem, sourceRecordId, occurredAt, payload, attachments }) {
  const topic = routeFor(department);
  for (const field of API_REQUIRED[department] || []) {
    if (payload?.[field] === undefined || payload?.[field] === null || payload?.[field] === '') {
      throw new Error(`missing required payload field for ${department}: ${field}`);
    }
  }
  return {
    eventId,
    sourceSystem,
    sourceRecordId,
    occurredAt,
    payload: coerce(department, payload || {}),
    attachments: attachments || [],
  };
}

// The §3.2 duplicate key — the same pair the worker upserts on and the dedup store indexes.
export function dedupKey(sourceSystem, sourceRecordId) {
  return `${sourceSystem}+${sourceRecordId}`;
}

// Topic-level validators used by the cross-service contract tests: they mirror the
// worker's FIELD_MAPS (required flags only; types are enforced at the API boundary).
export const VALIDATORS = Object.fromEntries(
  Object.entries(TOPIC_ROUTES).map(([dept, topic]) => [
    topic,
    (payload) => {
      const required = { complaints: [], traffic: [], water: ['sensorId', 'parameter'], health: [], ev: ['busId'] }[dept];
      for (const f of required) {
        if (payload?.[f] === undefined) throw new Error(`worker would reject: missing ${f}`);
      }
      return true;
    },
  ]),
);

// Shared hub: the app's injectable seams and this module's contract surface live on one
// object so tests can monkeypatch seams and import the contract from the same place.
globalThis.__ingestion = Object.assign(globalThis.__ingestion || {}, {
  buildEnvelope,
  dedupKey,
  routeFor,
  TOPIC_ROUTES,
  VALIDATORS,
});
