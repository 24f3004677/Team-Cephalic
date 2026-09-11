# app/serial_bridge.py
"""
Reads JSON lines from the ESP32 gateway over USB serial and persists
each reading into the SensorData table.
"""
import json
import threading
import time
from datetime import datetime

import serial
import serial.tools.list_ports

from app.models import db, SensorData, Node

BAUD_RATE = 115200
SERIAL_PORT = None         # None = auto-detect
_stop_flag = threading.Event()
_bridge_thread = None
_app = None


def _find_esp32_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").upper()
        if any(k in desc for k in ("ESP32", "CH340", "CP210", "USB SERIAL")):
            return p.device
    return ports[0].device if ports else None


def _store_payload(payload):
    with _app.app_context():
        node_id = int(payload.get("node_id", 0))
        node = Node.query.get(node_id)
        if node is None:
            print(f"[SERIAL] Unknown node_id={node_id}; dropping packet")
            return

        now = datetime.utcnow()
        for key, val in payload.items():
            if key in ("node_id", "ts_ms"):
                continue
            try:
                db.session.add(SensorData(
                    node_id=node_id,
                    sensor_type=key,
                    value=float(val),
                    timestamp=now,
                ))
            except (TypeError, ValueError):
                pass
        db.session.commit()


def _loop():
    port = SERIAL_PORT or _find_esp32_port()
    if port is None:
        print("[SERIAL] No ESP32 port detected; bridge disabled")
        return

    print(f"[SERIAL] Opening {port} @ {BAUD_RATE}")
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(2)
    except Exception as e:
        print(f"[SERIAL] Cannot open {port}: {e}")
        return

    while not _stop_flag.is_set():
        try:
            raw = ser.readline().decode("utf-8", errors="ignore").strip()
            if not raw or not raw.startswith("{"):
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            _store_payload(payload)
        except Exception as e:
            print(f"[SERIAL] Loop error: {e}")
            time.sleep(1)

    ser.close()


def start_serial_bridge(app):
    """Call from create_app() AFTER db.create_all(). Idempotent."""
    global _bridge_thread, _app
    _app = app
    if _bridge_thread and _bridge_thread.is_alive():
        return
    _stop_flag.clear()
    _bridge_thread = threading.Thread(
        target=_loop, daemon=True, name="ESP32-Serial-Bridge"
    )
    _bridge_thread.start()
    print("[SERIAL] Background serial bridge started")