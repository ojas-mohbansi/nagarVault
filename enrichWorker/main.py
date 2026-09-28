import asyncio
import json
import logging
import os
from datetime import datetime

import asyncpg
from aiokafka import AIOKafkaConsumer
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("enrich-worker")

BOOTSTRAP_SERVER = os.getenv("BOOTSTRAP_SERVER", "localhost:9092")
DATABASE_URL = os.getenv("DATABASE_URL")

TOPICS = [
    "nmc.complaints.raw.restricted.v1",
    "traffic.events.raw.v1",
    "water.sensors.raw.v1",
    "health.camps.raw.v1",
    "ev.bus.telemetry.raw.v1",
]


def _ts(value):
    """Parse an ISO-8601 timestamp string into a datetime for asyncpg."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

async def insert_nmc(conn, event):
    payload = event.get("payload", {})
    await conn.execute("""
        INSERT INTO nmc_complaints (event_id, ward_id, category, description, status, source_record_id, source_system, sensitivity, created_at, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9) ON CONFLICT DO NOTHING
        """,
        event.get("eventId"), event.get("location", {}).get("wardId", "UNKNOWN"),
        payload.get("category", "unknown"), payload.get("description"),
        payload.get("status", "open"), event.get("sourceRecordId"),
        event.get("sourceSystem"), event.get("sensitivity", "restricted"), _ts(event.get("receivedAt")),
    )

async def insert_traffic(conn, event):
    payload = event.get("payload", {})
    await conn.execute("""
        INSERT INTO traffic_events (source_record_id, ward_id, junction, severity, event_type, average_speed_kmph, vehicle_count, camera_id, rain_detected, occurred_at, received_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT DO NOTHING
        """,
        event.get("sourceRecordId"), event.get("location", {}).get("wardId", "UNKNOWN"),
        payload.get("junction"), payload.get("severity", "low"), event.get("eventType"),
        payload.get("averageSpeedKmph"), payload.get("vehicleCount"), payload.get("cameraId"),
        bool(payload.get("rainDetected", False)), _ts(event.get("occurredAt")), _ts(event.get("receivedAt")),
    )

async def insert_water(conn, event):
    payload = event.get("payload", {})
    alert = payload.get("status", "normal") != "normal"
    await conn.execute("""
        INSERT INTO water_sensor_readings (source_record_id, sensor_id, asset_name, ward_id, pressure_bar, flow_lpm, level_cm, status, alert_raised, event_type, occurred_at, received_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT DO NOTHING
        """,
        event.get("sourceRecordId"), payload.get("sensorId", "UNKNOWN"), payload.get("assetName"),
        event.get("location", {}).get("wardId", "UNKNOWN"), payload.get("pressureBar"),
        payload.get("flowLpm"), payload.get("levelCm"), payload.get("status", "normal"),
        alert, event.get("eventType"), _ts(event.get("occurredAt")), _ts(event.get("receivedAt")),
    )

async def insert_health(conn, event):
    payload = event.get("payload", {})
    services = payload.get("services", [])
    if isinstance(services, str):
        services = [services]
    await conn.execute("""
        INSERT INTO health_camp_records (source_record_id, facility_name, ward_id, services, capacity, registered_patients, waiting_patients, average_wait_minutes, camp_status, event_type, occurred_at, received_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT DO NOTHING
        """,
        event.get("sourceRecordId"), payload.get("facilityName", "Unknown Facility"),
        event.get("location", {}).get("wardId", "UNKNOWN"), services,
        payload.get("capacity"), payload.get("registeredPatients"), payload.get("waitingPatients"),
        payload.get("averageWaitMinutes"), payload.get("campStatus", "active"),
        event.get("eventType"), _ts(event.get("occurredAt")), _ts(event.get("receivedAt")),
    )

async def insert_transport(conn, event):
    payload = event.get("payload", {})
    await conn.execute("""
        INSERT INTO ev_bus_telemetry (source_record_id, bus_id, route_id, ward_id, speed_kmph, battery_soc, passenger_count, bus_status, event_type, occurred_at, received_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT DO NOTHING
        """,
        event.get("sourceRecordId"), payload.get("busId", "UNKNOWN"), payload.get("routeId"),
        event.get("location", {}).get("wardId", "UNKNOWN"), payload.get("speedKmph"),
        payload.get("batterySoc"), payload.get("passengerCount"),
        payload.get("status", "in-service"), event.get("eventType"),
        _ts(event.get("occurredAt")), _ts(event.get("receivedAt")),
    )

TOPIC_HANDLERS = {
    "nmc.complaints.raw.restricted.v1": insert_nmc,
    "traffic.events.raw.v1": insert_traffic,
    "water.sensors.raw.v1": insert_water,
    "health.camps.raw.v1": insert_health,
    "ev.bus.telemetry.raw.v1": insert_transport,
}

async def process_message(pool: asyncpg.Pool, topic: str, event: dict):
    handler = TOPIC_HANDLERS.get(topic)
    if handler is None:
        log.warning(f"No handler for topic {topic!r}")
        return
    async with pool.acquire() as conn:
        await handler(conn, event)
    log.info(f"[{topic}] stored sourceRecordId={event.get('sourceRecordId')!r}")

async def run():
    log.info("Creating asyncpg connection pool...")
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    log.info(f"Connected to PostgreSQL. Subscribing to {len(TOPICS)} topics.")

    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=BOOTSTRAP_SERVER,
        value_deserializer=lambda x: json.loads(x.decode("utf-8")),
        group_id="enrich-group",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    log.info("Listening for messages...")

    try:
        async for msg in consumer:
            event = msg.value
            try:
                await process_message(pool, msg.topic, event)
                # Commit the offset only after the DB write has been confirmed
                await consumer.commit()
            except Exception as exc:
                log.error(f"[{msg.topic}] failed to store event, not committing offset: {exc}")
    finally:
        await consumer.stop()
        await pool.close()

if __name__ == "__main__":
    asyncio.run(run())
