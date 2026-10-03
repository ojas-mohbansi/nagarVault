# enrichWorker — Kafka → PostgreSQL enrichment (no HTTP port; consumer), Phase 7c fresh
# rebuild (ADR-013).
#
# CONTRACTS (verbatim — ARCHITECTURE §3.3 enrichment flow, §3.2 ingestion invariants,
# §4.2 topic registry, Phase-5 DDL department tables):
#   * consumes the five raw topics: health.camps.raw.v1, nmc.complaints.raw.restricted.v1,
#     traffic.events.raw.v1, water.sensors.raw.v1, ev.bus.telemetry.raw.v1
#   * normalizes per department and UPSERTS into the matching table; the dedup key is the
#     (source_system, source_record_id) pair — at-least-once redelivery upserts, never
#     duplicates (UNIQUE constraints in migration 001 are the last wall)
#   * malformed events (bad JSON, missing required fields, wrong types, unknown department)
#     are published to nmc.complaints.dlq.v1 and never crash the loop; the DLQ CONSUMER is
#     adminService (7f) — this worker is the DLQ PRODUCER
#   * a DATA-level database error (a per-message psycopg error that is not a connection failure,
#     e.g. an invalid occurred_at the DB rejects) is likewise quarantined to the DLQ, so one bad
#     event cannot become a poison pill that halts the tier; connection-level failures still
#     propagate (a DB outage is a readiness problem, not the message's fault)
#   * media never passes through Kafka: only bucket/objectKey references (§3.2)
#   * every processed message is committed only after its DB write or DLQ publish succeeds
#     (no silent loss on the happy path)
#
# Wire envelope (derived from the migration-001 column contract + §3.2 field names; the
# canonical contract for the 7e ingestion producer):
#   {
#     "eventId": "unique-ingestion-id",
#     "sourceSystem": "<external system name>",
#     "sourceRecordId": "<id in that system>",
#     "occurredAt": "ISO-8601 timestamp",
#     "payload": { department-specific fields, below },
#     "attachments": [{"bucket": "...", "objectKey": "..."}]   # optional, references only
#   }
#   nmc_complaints payload:   ward, category, status, description
#   traffic_events payload:   junction, corridor, direction, eventType, severity,
#                             vehicleCount (int), averageSpeed (number)
#   water_sensor_readings:    sensorId (req), parameter (req), value (number), unit, qualityFlag
#   health_camp_records:      campId, patientRef, ageBand, sex, screeningType, diagnosis, referral
#   ev_bus_telemetry:         busId (req), routeId, latitude, longitude (numbers),
#                             speedKph, stateOfCharge (numbers)
#
# Structure: pure handler (handle_message -> Outcomes) + a thin confluent-kafka loop. The
# handler and SQL construction are fully tested hermetically (tests/test_enrich.py); the
# loop is exercised live in-cluster (G7c.4).
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import psycopg

log = logging.getLogger("enrichWorker")

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "nagar-kafka-bootstrap.nagar-platform.svc.cluster.local:29092")
GROUP_ID = os.environ.get("KAFKA_GROUP_ID", "enrichWorker")
DLQ_TOPIC = "nmc.complaints.dlq.v1"  # frozen name, ARCHITECTURE §4.2

TOPIC_TABLE = {
    "nmc.complaints.raw.restricted.v1": "nmc_complaints",
    "traffic.events.raw.v1": "traffic_events",
    "water.sensors.raw.v1": "water_sensor_readings",
    "health.camps.raw.v1": "health_camp_records",
    "ev.bus.telemetry.raw.v1": "ev_bus_telemetry",
}

# payload keys -> table columns, with required flags and python types.
# Column names come from migration 001; the mapping is the only place topic-specific
# normalization lives.
FIELD_MAPS = {
    "nmc_complaints": {"ward": False, "category": False, "status": False, "description": False},
    "traffic_events": {"junction": False, "corridor": False, "direction": False,
                       "eventType": False, "severity": False,
                       "vehicleCount": False, "averageSpeed": False},
    "water_sensor_readings": {"sensorId": True, "parameter": True, "value": False,
                              "unit": False, "qualityFlag": False},
    "health_camp_records": {"campId": False, "patientRef": False, "ageBand": False, "sex": False,
                            "screeningType": False, "diagnosis": False, "referral": False},
    "ev_bus_telemetry": {"busId": True, "routeId": False, "latitude": False, "longitude": False,
                         "speedKph": False, "stateOfCharge": False},
}
# Tables whose DDL carries media_bucket/media_object_key (migration 001). Keep in step with
# 05-postgres/migrations/001_create_tables.sql.
MEDIA_TABLES = {"nmc_complaints", "traffic_events"}

INT_FIELDS = {"vehicleCount"}
FLOAT_FIELDS = {"averageSpeed", "value", "latitude", "longitude", "speedKph", "stateOfCharge"}
CAMEL_TO_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")

# Connection-level failures (the database is unreachable / the connection is broken). These are
# NOT the message's fault, so they must keep propagating: the consumer loop lets them surface
# rather than quarantining a perfectly good event. Every other psycopg error is a DATA-level
# defect in this one message (bad timestamp, value too long, DDL drift, …) and is quarantined to
# the DLQ instead of killing the worker — see process_message.
DB_CONNECTION_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError)


@dataclass
class Outcomes:
    upserts: list = field(default_factory=list)    # (table, sql, params)
    dlq: list = field(default_factory=list)        # (reason, detail, raw_bytes)


def _fail(outcomes: Outcomes, reason: str, detail: str, raw: bytes) -> None:
    outcomes.dlq.append((reason, detail, raw))


def snake(name: str) -> str:
    return CAMEL_TO_SNAKE.sub("_", name).lower()


def build_upsert(table: str, envelope: dict, columns: dict) -> tuple[str, tuple]:
    """INSERT ... ON CONFLICT upsert on the (source_system, source_record_id) dedup key.
    Re-delivery overwrites the row with the latest enrichment (I-2: idempotent re-run)."""
    # Only nmc_complaints and traffic_events carry media columns (migration 001); water, health
    # and ev tables do not. Emitting media_bucket/media_object_key for those three raised
    # `UndefinedColumn` inside the consumer loop, which killed the worker process and left every
    # later department unenriched — found by G10.2, the first time those topics were ever
    # exercised (traffic/complaints had carried every prior gate, so the bug never surfaced).
    cols = ["event_id", "source_system", "source_record_id", "occurred_at", "payload"]
    if table in MEDIA_TABLES:
        cols += ["media_bucket", "media_object_key"]
    cols += list(columns.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    # Identity columns stay; everything else (incl. occurred_at, payload, media refs)
    # refreshes from the latest envelope on conflict — at-least-once redelivery wins.
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[3:])
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT (source_system, source_record_id) DO UPDATE SET {updates}")
    media = []
    if table in MEDIA_TABLES:
        first = (envelope.get("attachments") or [{}])[0]
        media = [first.get("bucket"), first.get("objectKey")]
    params = (
        envelope["eventId"], envelope["sourceSystem"], envelope["sourceRecordId"],
        envelope["occurredAt"], json.dumps(envelope.get("payload", {})),
        *media,
        *columns.values(),
    )
    return sql, params


def validate_envelope(envelope: dict, table: str) -> dict:
    """Returns {column: value} for the department fields; raises ValueError on any defect."""
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    out = {}
    for key, required in FIELD_MAPS[table].items():
        value = payload.get(key)
        if value is None:
            if required:
                raise ValueError(f"missing required payload field: {key}")
            continue
        if key in INT_FIELDS:
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"field {key} must be an integer")
        elif key in FLOAT_FIELDS:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"field {key} must be a number")
        else:
            value = str(value)
        out[snake(key)] = value
    return out


def handle_message(topic: str, raw: bytes) -> Outcomes:
    """Pure handler: raw Kafka bytes -> upserts and/or DLQ entries. Never raises."""
    outcomes = Outcomes()
    table = TOPIC_TABLE.get(topic)
    if table is None:
        _fail(outcomes, "unknown-topic", f"no mapping for topic {topic}", raw)
        return outcomes
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _fail(outcomes, "invalid-json", "body is not valid UTF-8 JSON", raw)
        return outcomes
    if not isinstance(envelope, dict):
        _fail(outcomes, "invalid-envelope", "envelope must be a JSON object", raw)
        return outcomes
    for req_field in ("eventId", "sourceSystem", "sourceRecordId", "occurredAt"):
        if not envelope.get(req_field) or not isinstance(envelope[req_field], str):
            _fail(outcomes, "invalid-envelope", f"missing or non-string {req_field}", raw)
            return outcomes
    try:
        columns = validate_envelope(envelope, table)
    except ValueError as e:
        _fail(outcomes, "invalid-payload", str(e), raw)
        return outcomes
    sql, params = build_upsert(table, envelope, columns)
    outcomes.upserts.append((table, sql, params))
    return outcomes


# --------------------------------------------------------------------------- seams


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)


def upsert_batch(upserts: list) -> int:
    executed = 0
    with connect() as conn, conn.cursor() as cur:
        for _table, sql, params in upserts:
            cur.execute(sql, params)
            executed += 1
        conn.commit()
    return executed


def record_to_dlq(entries: list, original_topic: str) -> None:
    """Publish malformed messages to the DLQ (produced by this worker, consumed by 7f)."""
    if not entries:
        return
    from confluent_kafka import Producer

    producer = Producer({"bootstrap.servers": BOOTSTRAP})
    for reason, detail, raw in entries:
        wrapper = json.dumps({
            "dlqReason": reason,
            "detail": detail,
            "originalTopic": original_topic,
            "raw": raw.decode("utf-8", "replace"),
        }).encode()
        producer.produce(DLQ_TOPIC, value=wrapper)
    producer.flush(30)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_message(topic: str, raw: bytes) -> str:
    """One message through the full path; returns 'upserted' | 'db-error' | 'dlq'.

    A DATA-level database error (a per-message psycopg error that is not a connection failure)
    is quarantined to the DLQ and the message is acknowledged, rather than propagating and
    killing the consumer. Before this guard the loop committed only after `process_message`
    returned, so a single message the DB rejected left the offset uncommitted and the worker
    re-polled the same message on every restart — a poison-pill CrashLoopBackOff that halted
    the entire enrichment tier (found live by G11).

    Connection-level failures still raise: a database outage is a readiness problem, not a
    property of the message, and must not drain the topic into the DLQ.
    """
    outcomes = handle_message(topic, raw)
    if outcomes.upserts:
        try:
            upsert_batch(outcomes.upserts)
        except DB_CONNECTION_ERRORS:
            raise
        except psycopg.Error as e:
            outcomes.upserts.clear()
            _fail(outcomes, "db-error", f"{type(e).__name__}: {e}", raw)
    if outcomes.dlq:
        record_to_dlq(outcomes.dlq, topic)
        return "db-error" if any(reason == "db-error" for reason, _d, _r in outcomes.dlq) else "dlq"
    return "upserted"


def run_consumer() -> None:
    """Long-running consume loop (the Deployment's only job). Lazy import keeps the
    hermetic suite free of the Kafka dependency."""
    from confluent_kafka import Consumer

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP_ID,
        "enable.auto.commit": False,          # commit only after the DB write / DLQ publish
        "auto.offset.reset": "earliest",
    })
    consumer.subscribe(list(TOPIC_TABLE))
    log.info("enrichWorker subscribed to %s (group %s)", list(TOPIC_TABLE), GROUP_ID)
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                log.warning("kafka error: %s", msg.error())
                continue
            verdict = process_message(msg.topic(), msg.value())
            consumer.commit(message=msg, asynchronous=False)
            log.info("%s %s -> %s", msg.topic(), msg.key(), verdict)
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run_consumer()
