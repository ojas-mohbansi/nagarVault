# enrichWorker test suite — Phase 7c (hermetic; no Kafka, no database).
#
# CONTRACT UNDER TEST (ARCHITECTURE §3.3/§3.2/§4.2, Phase-5 DDL):
#   * valid envelope -> one upsert per message on the right table, dedup key
#     (source_system, source_record_id), payload + media refs carried through
#   * malformed input (bad JSON, non-object, missing envelope fields, bad payload
#     types, missing required fields, unknown topic) -> DLQ entry with a reason,
#     never an exception
#   * numeric coercion (vehicleCount int; speeds/coords/SoC floats)
#   * build_upsert SQL shape: ON CONFLICT (source_system, source_record_id) with
#     refresh of enrichment columns on conflict (idempotent redelivery)
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import enrich as ew  # noqa: E402


def envelope(**payload):
    return {
        "eventId": "evt-1",
        "sourceSystem": "nmc-crm",
        "sourceRecordId": "REC-42",
        "occurredAt": "2026-09-30T10:00:00Z",
        "payload": payload,
    }


# --------------------------------------------------------------------------- happy paths


def test_valid_complaint_yields_upsert():
    out = ew.handle_message("nmc.complaints.raw.restricted.v1",
                            json.dumps(envelope(ward="1", category="sanitation",
                                                status="open", description="clogged drain")).encode())
    assert not out.dlq
    assert len(out.upserts) == 1
    table, sql, params = out.upserts[0]
    assert table == "nmc_complaints"
    assert "INSERT INTO nmc_complaints" in sql
    assert "ON CONFLICT (source_system, source_record_id)" in sql
    # params: eventId, sourceSystem, sourceRecordId, occurredAt, payload, bucket, key, ward...
    assert params[0] == "evt-1" and params[1] == "nmc-crm" and params[2] == "REC-42"


def test_media_references_carried_not_bytes():
    env = envelope(ward="2")
    env["attachments"] = [{"bucket": "raw-media", "objectKey": "complaints/REC-42.jpg"}]
    env["payload"]["description"] = "see photo"
    out = ew.handle_message("nmc.complaints.raw.restricted.v1", json.dumps(env).encode())
    params = out.upserts[0][2]
    assert params[5] == "raw-media"
    assert params[6] == "complaints/REC-42.jpg"
    assert b"JFIF" not in json.dumps(json.loads(json.dumps(env))).encode()  # no bytes anywhere


def column_params(table, sql, params, column):
    """Resolve a param by name: the INSERT column list is params-aligned 1:1."""
    cols = [c.strip() for c in sql.split("(", 2)[1].split(")")[0].split(",")]
    return params[cols.index(column)]


def test_traffic_numeric_coercion():
    table, sql, params = ew.handle_message(
        "traffic.events.raw.v1",
        json.dumps(envelope(junction="A1", direction="north", eventType="congestion",
                            severity="high", vehicleCount="42", averageSpeed="7.5")).encode()).upserts[0]
    assert table == "traffic_events"
    assert column_params(table, sql, params, "vehicle_count") == 42
    assert column_params(table, sql, params, "average_speed") == 7.5
    assert column_params(table, sql, params, "junction") == "A1"


def test_ev_telemetry_coords():
    table, sql, params = ew.handle_message(
        "ev.bus.telemetry.raw.v1",
        json.dumps(envelope(busId="BUS-7", latitude="12.9716", longitude="77.5946",
                            speedKph="31.4", stateOfCharge="88.0")).encode()).upserts[0]
    assert table == "ev_bus_telemetry"
    assert column_params(table, sql, params, "bus_id") == "BUS-7"
    assert column_params(table, sql, params, "latitude") == 12.9716
    assert column_params(table, sql, params, "state_of_charge") == 88.0


def test_water_required_fields():
    out = ew.handle_message("water.sensors.raw.v1",
                            json.dumps(envelope(sensorId="W-12", parameter="ph",
                                                value="7.2", unit="pH")).encode())
    table, sql, params = out.upserts[0]
    assert table == "water_sensor_readings"
    assert column_params(table, sql, params, "sensor_id") == "W-12"
    assert column_params(table, sql, params, "value") == 7.2


def test_health_mapping():
    out = ew.handle_message("health.camps.raw.v1",
                            json.dumps(envelope(campId="C-1", patientRef="P-9",
                                                screeningType="bp-check")).encode())
    assert out.upserts[0][0] == "health_camp_records"


# --------------------------------------------------------------------------- DLQ paths


@pytest.mark.parametrize("raw", [b"", b"not json", b"\xff\xfe\xfd"])
def test_invalid_json_goes_to_dlq(raw):
    out = ew.handle_message("traffic.events.raw.v1", raw)
    assert not out.upserts
    assert len(out.dlq) == 1
    reason, _detail, _raw = out.dlq[0]
    assert reason == "invalid-json"


def test_non_object_envelope_goes_to_dlq():
    out = ew.handle_message("traffic.events.raw.v1", b"[1,2,3]")
    assert out.dlq[0][0] == "invalid-envelope"


@pytest.mark.parametrize("missing", ["eventId", "sourceSystem", "sourceRecordId", "occurredAt"])
def test_missing_envelope_field_goes_to_dlq(missing):
    env = envelope(junction="A1")
    env.pop(missing)
    out = ew.handle_message("traffic.events.raw.v1", json.dumps(env).encode())
    assert not out.upserts
    assert out.dlq[0][0] == "invalid-envelope"
    assert missing in out.dlq[0][1]


def test_missing_required_payload_field_goes_to_dlq():
    out = ew.handle_message("water.sensors.raw.v1", json.dumps(envelope(parameter="ph")).encode())
    assert out.dlq[0][0] == "invalid-payload"
    assert "sensorId" in out.dlq[0][1]


def test_wrong_type_goes_to_dlq():
    out = ew.handle_message("traffic.events.raw.v1",
                            json.dumps(envelope(vehicleCount="many")).encode())
    assert out.dlq[0][0] == "invalid-payload"
    assert "vehicleCount" in out.dlq[0][1]


def test_unknown_topic_goes_to_dlq():
    out = ew.handle_message("topics.that.dont.exist.v1", b"{}")
    assert out.dlq[0][0] == "unknown-topic"


def test_payload_not_object_goes_to_dlq():
    env = envelope()
    env["payload"] = "stringy"
    out = ew.handle_message("nmc.complaints.raw.restricted.v1", json.dumps(env).encode())
    assert out.dlq[0][0] == "invalid-payload"


# --------------------------------------------------------------------------- upsert shape


def test_upsert_refreshes_enrichment_on_conflict():
    sql, _params = ew.build_upsert("nmc_complaints", envelope(ward="1"), {"ward": "1"})
    assert "ON CONFLICT (source_system, source_record_id) DO UPDATE" in sql
    assert "ward = EXCLUDED.ward" in sql
    assert "event_id = EXCLUDED.event_id" not in sql  # identity columns stay


def test_upsert_media_columns_only_where_the_ddl_has_them():
    """Regression for the G10.2 worker crash.

    Only nmc_complaints and traffic_events carry media_bucket/media_object_key (migration 001).
    The upsert used to emit both columns for EVERY table, so the first water/health/ev event
    raised psycopg.errors.UndefinedColumn inside the consumer loop and killed the worker —
    taking every later department down with it. Those three topics had never been exercised
    before G10.2, which is why the suite stayed green.
    """
    for table in ("nmc_complaints", "traffic_events"):
        sql, params = ew.build_upsert(table, envelope(ward="1"), {"ward": "1"})
        assert "media_bucket" in sql and "media_object_key" in sql, table
        # 5 identity columns + 2 media + 1 department column
        assert len(params) == 8, table
    for table in ("water_sensor_readings", "health_camp_records", "ev_bus_telemetry"):
        sql, params = ew.build_upsert(table, envelope(sensorId="s1"), {"sensor_id": "s1"})
        assert "media_bucket" not in sql and "media_object_key" not in sql, table
        # event_id, source_system, source_record_id, occurred_at, payload, <dept columns>
        assert len(params) == 6, table
    # The column list and the value list must stay the same length for every table.
    for table in ew.MEDIA_TABLES | {"water_sensor_readings", "health_camp_records", "ev_bus_telemetry"}:
        sql, params = ew.build_upsert(table, envelope(ward="1"), {"ward": "1"})
        cols = sql.split("INSERT INTO %s (" % table)[1].split(")")[0].split(", ")
        assert len(cols) == len(params), table


def test_process_message_routes(monkeypatch):
    calls = {"upserts": 0, "dlq": 0}
    monkeypatch.setattr(ew, "upsert_batch", lambda ups: calls.__setitem__("upserts", calls["upserts"] + len(ups)))
    monkeypatch.setattr(ew, "record_to_dlq", lambda entries, topic: calls.__setitem__("dlq", calls["dlq"] + len(entries)))
    assert ew.process_message("nmc.complaints.raw.restricted.v1", json.dumps(envelope(ward="1")).encode()) == "upserted"
    assert ew.process_message("nmc.complaints.raw.restricted.v1", b"junk") == "dlq"
    assert calls == {"upserts": 1, "dlq": 1}


def test_snake_case_mapping():
    assert ew.snake("vehicleCount") == "vehicle_count"
    assert ew.snake("stateOfCharge") == "state_of_charge"
    assert ew.snake("ward") == "ward"
