# ============================================================
# app/serial_bridge.py
#
# ESP32-S3 USB Serial Gateway
#
# Reads JSON lines from the ESP32-S3 receiver and stores
# every sensor value into the SensorData database table.
#
# ESP32-S3 -> USB -> Python -> SQLite
# ============================================================

import json
import importlib
import threading
import time
from datetime import datetime


# ============================================================
# SERIAL LIBRARY
# ============================================================

try:
    serial = importlib.import_module("serial")
    list_ports = importlib.import_module("serial.tools.list_ports")

except ImportError:

    serial = None
    list_ports = None


# ============================================================
# DATABASE
# ============================================================

from app.models import db, SensorData, Node


# ============================================================
# CONFIGURATION
# ============================================================

BAUD_RATE = 115200

# ------------------------------------------------------------
# IMPORTANT:
#
# Your ESP32-S3 receiver is currently on COM4.
#
# If Windows gives it another COM number later,
# change this value.
# ------------------------------------------------------------

SERIAL_PORT = "COM6"


# ============================================================
# THREAD CONTROL
# ============================================================

_stop_flag = threading.Event()

_bridge_thread = None

_app = None


# ============================================================
# AUTOMATIC PORT DETECTION
# ============================================================

def _find_esp32_port():

    if list_ports is None:

        return None


    ports = list_ports.comports()


    for p in ports:

        desc = (p.description or "").upper()


        if any(
            key in desc
            for key in (
                "ESP32",
                "CH340",
                "CP210",
                "USB SERIAL"
            )
        ):

            return p.device


    # Fallback

    return ports[0].device if ports else None


# ============================================================
# STORE ONE JSON PAYLOAD
# ============================================================

def _store_payload(payload):

    with _app.app_context():

        # ----------------------------------------------------
        # Get node ID
        # ----------------------------------------------------

        try:

            node_id = int(
                payload.get("node_id", 0)
            )

        except (TypeError, ValueError):

            print(
                "[SERIAL] Invalid node_id; dropping packet"
            )

            return


        # ----------------------------------------------------
        # Check that node exists in database
        # ----------------------------------------------------

        node = Node.query.get(node_id)


        if node is None:

            print(
                f"[SERIAL] Unknown node_id={node_id}; "
                f"dropping packet"
            )

            return


        # ----------------------------------------------------
        # Timestamp
        #
        # We use the laptop's UTC reception time as the
        # database timestamp.
        #
        # This is better for the website/database because
        # millis() on the ESP32 is only time since boot.
        # ----------------------------------------------------

        now = datetime.utcnow()


        stored_count = 0


        # ----------------------------------------------------
        # Store every sensor value
        # ----------------------------------------------------

        for key, val in payload.items():

            # These are metadata, not sensor measurements.

            if key in (
                "node_id",
                "ts_ms"
            ):

                continue


            try:

                numeric_value = float(val)


                db.session.add(
                    SensorData(
                        node_id=node_id,
                        sensor_type=key,
                        value=numeric_value,
                        timestamp=now
                    )
                )


                stored_count += 1


            except (
                TypeError,
                ValueError
            ):

                print(
                    f"[SERIAL] Invalid value "
                    f"for {key}: {val}"
                )


        # ----------------------------------------------------
        # Commit entire packet
        # ----------------------------------------------------

        if stored_count > 0:

            db.session.commit()


            print(
                f"[SERIAL] Node {node_id}: "
                f"stored {stored_count} sensor values"
            )


# ============================================================
# SERIAL READING LOOP
# ============================================================

def _loop():

    # --------------------------------------------------------
    # Check PySerial
    # --------------------------------------------------------

    if serial is None:

        print(
            "[SERIAL] pyserial is not installed."
        )

        print(
            "[SERIAL] Bridge disabled."
        )

        return


    # --------------------------------------------------------
    # Determine port
    # --------------------------------------------------------

    port = (
        SERIAL_PORT
        or _find_esp32_port()
    )


    if port is None:

        print(
            "[SERIAL] No ESP32 serial port detected."
        )

        print(
            "[SERIAL] Bridge disabled."
        )

        return


    print()
    print(
        "========================================"
    )

    print(
        "[SERIAL] ESP32-S3 SERIAL BRIDGE"
    )

    print(
        "========================================"
    )

    print(
        f"[SERIAL] Port : {port}"
    )

    print(
        f"[SERIAL] Baud : {BAUD_RATE}"
    )

    print()


    # --------------------------------------------------------
    # Open serial port
    # --------------------------------------------------------

    try:

        ser = serial.Serial(
            port,
            BAUD_RATE,
            timeout=1
        )


        # Give ESP32 time to reset after opening port

        time.sleep(2)


        print(
            "[SERIAL] Serial connection established."
        )

        print(
            "[SERIAL] Waiting for JSON sensor data..."
        )

        print()


    except Exception as e:

        print(
            f"[SERIAL] Cannot open {port}: {e}"
        )

        return


    # ========================================================
    # MAIN SERIAL LOOP
    # ========================================================

    while not _stop_flag.is_set():

        try:

            # ------------------------------------------------
            # Read one line
            # ------------------------------------------------

            raw_bytes = ser.readline()


            if not raw_bytes:

                continue


            # ------------------------------------------------
            # Decode
            # ------------------------------------------------

            raw = raw_bytes.decode(
                "utf-8",
                errors="ignore"
            ).strip()


            # ------------------------------------------------
            # Ignore non-JSON startup/debug lines
            # ------------------------------------------------

            if not raw:

                continue


            if not raw.startswith("{"):

                continue


            # ------------------------------------------------
            # Parse JSON
            # ------------------------------------------------

            try:

                payload = json.loads(raw)

            except json.JSONDecodeError as e:

                print(
                    "[SERIAL] Invalid JSON:"
                )

                print(raw)

                continue


            # ------------------------------------------------
            # Validate payload
            # ------------------------------------------------

            if not isinstance(
                payload,
                dict
            ):

                print(
                    "[SERIAL] JSON payload is not an object."
                )

                continue


            if "node_id" not in payload:

                print(
                    "[SERIAL] JSON packet has no node_id."
                )

                continue


            # ------------------------------------------------
            # Store in database
            # ------------------------------------------------

            _store_payload(payload)


        except Exception as e:

            print(
                f"[SERIAL] Loop error: {e}"
            )


            # Prevent rapid error loop

            time.sleep(1)


    # ========================================================
    # CLEANUP
    # ========================================================

    try:

        ser.close()

    except Exception:

        pass


    print(
        "[SERIAL] Serial bridge stopped."
    )


# ============================================================
# START SERIAL BRIDGE
# ============================================================

def start_serial_bridge(app):

    """
    Start the ESP32 serial bridge.

    Called from create_app() after database creation.

    Idempotent: calling it more than once does not create
    multiple serial-reading threads.
    """

    global _bridge_thread
    global _app


    _app = app


    # --------------------------------------------------------
    # Don't create duplicate thread
    # --------------------------------------------------------

    if (
        _bridge_thread
        and _bridge_thread.is_alive()
    ):

        print(
            "[SERIAL] Bridge already running."
        )

        return


    # --------------------------------------------------------
    # Start
    # --------------------------------------------------------

    _stop_flag.clear()


    _bridge_thread = threading.Thread(

        target=_loop,

        daemon=True,

        name="ESP32-Serial-Bridge"
    )


    _bridge_thread.start()


    print(
        "[SERIAL] Background serial bridge started"
    )
