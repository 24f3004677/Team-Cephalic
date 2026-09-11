# app/serial_bridge.py
"""
Reads JSON lines from the ESP32 receiver over USB serial and
persists them into the SensorData table.
"""
import json
import threading
import time
from datetime import datetime

import serial
import serial.tools.list_ports

from app.models import db, SensorData, Node

# Configuration
BAUD_RATE = 115200
SERIAL_PORT = None          # auto-detected if None
STOP_FLAG = threading.Event()
_bridge_thread = None


def find_esp32_port():
    """Try to auto-detect the ESP32 serial port."""
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if "ESP32" in p.description or "CH340" in p.description or "CP210" in p.description:
            return p.device
    # Fallback: return first available port
    return ports[0].device if ports else None


def _ingest_payload(app, payload):
    """
    payload is a dict coming from the JSON line, e.g.
    {"node_id":1, "rotation_x":1.23, ..., "ts_ms":12345}
    """
    with app.app_context():
        node_id = int(payload["node_id"])
        node = Node.query.get(node_id)
        if not node:
            print(f"[SERIAL] Unknown node_id {node_id}; skipping")
            return

        # Every non-identifier key becomes a SensorData row
        # (skip node_id and ts_ms)
        for key, value in payload.items():
            if key in ("node_id", "ts_ms"):
                continue
            db.session.add(SensorData(
                node_id=node_id,
                sensor_type=key,
                value=float(value),
                timestamp=datetime.utcnow()
            ))
        db.session.commit()
        print(f"[SERIAL] Stored {len(payload)-2} readings for node {node_id}")


def _serial_loop(app):
    """Continuous read loop — runs in a background thread."""
    port = SERIAL_PORT or find_esp32_port()
    if port is None:
        print("[SERIAL] No ESP32 serial port found; bridge disabled")
        return

    print(f"[SERIAL] Opening {port} at {BAUD_RATE} baud")
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(2)   # allow ESP32 to reset after port open
    except Exception as e:
        print(f"[SERIAL] Could not open port: {e}")
        return

    buffer = ""
    while not STOP_FLAG.is_set():
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            # Try parsing as JSON
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Ignore boot messages / non-JSON lines
                continue

            _ingest_payload(app, payload)

        except Exception as e:
            print(f"[SERIAL] Read error: {e}")
            time.sleep(1)

    ser.close()
    print("[SERIAL] Bridge stopped")


def start_serial_bridge(app):
    """Idempotent starter — call from create_app() AFTER db.create_all()."""
    global _bridge_thread
    if _bridge_thread and _bridge_thread.is_alive():
        return
    STOP_FLAG.clear()
    _bridge_thread = threading.Thread(
        target=_serial_loop, args=(app,),
        daemon=True, name="ESP32-Serial-Bridge"
    )
    _bridge_thread.start()
    print("[SERIAL] Background bridge thread started.")