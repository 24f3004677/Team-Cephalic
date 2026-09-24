"""
ML Engine integration layer.
- Loads StructuralAnomalyEngine once (singleton)
- Runs a background thread that:
    * pulls recent SensorData rows per node from the DB
    * runs the engine (per-node buffer)
    * persists AnalysisLog + Node/Mine status + Alert
- Falls back to the simulator ONLY when the DB has no fresh data.
"""
import os
import threading
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Import your engine
from universal_engine import StructuralAnomalyEngine

# ---------------------------------------------------------------------
# Path resolution  *** DO NOT CHANGE THESE THREE LINES ***
# ---------------------------------------------------------------------
APP_DIR       = Path(__file__).resolve().parent          # .../Team-Cephalic/app
TEAM_CEPHALIC = Path(__file__).resolve().parents[1]      # .../Team-Cephalic
PROJECT_ROOT  = Path(__file__).resolve().parents[2]      # .../DL_backend

MODELS_DIR = Path(os.environ.get("MODELS_DIR", TEAM_CEPHALIC / "models"))
STATIC_DIR = APP_DIR / "static"

_engine = None
_engine_error = None
_engine_lock = threading.Lock()
_bg_thread = None
_stop_flag = threading.Event()

# Config
TICK_INTERVAL_SECONDS = 2
USE_DB_SENSORS        = True
SIMULATE_IF_EMPTY     = True       # set False in production
ALERT_COOLDOWN_SECS   = 60
STALE_DATA_SECONDS    = 15

# Map DB sensor_type -> engine key
SENSOR_ALIASES = {
    # ESP-32 gateway keys
    "accel_x":             "acceleration_x",
    "accel_y":             "acceleration_y",
    "accel_z":             "acceleration_z",
    "rotation_x":          "rotation_x",
    "rotation_y":          "rotation_y",
    "rotation_z":          "rotation_z",
    "roof_convergence_cm": "roof_convergence_cm",
    "temperature":         "temperature",
    "humidity":            "humidity",
    "roof_convergence":    "roof_convergence_cm",
}

# Populate ML-track column names from their DL equivalents
ML_TRACK_ALIASES = {
    "acceleration_x": "Accel_X (m/s^2)",
    "acceleration_y": "Accel_Y (m/s^2)",
    "acceleration_z": "Accel_Z (m/s^2)",
    "temperature":    "Temp (°C)",
    "strain":         "Strain (με)",
}


def _alias(sensor_type: str) -> str:
    return SENSOR_ALIASES.get(sensor_type, sensor_type)


# ---------------------------------------------------------------
# Engine singleton
# ---------------------------------------------------------------
def get_engine():
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    if _engine_error is not None:
        raise _engine_error

    with _engine_lock:
        if _engine is not None:
            return _engine
        if _engine_error is not None:
            raise _engine_error

        try:
            STATIC_DIR.mkdir(parents=True, exist_ok=True)
            if not MODELS_DIR.is_dir():
                raise RuntimeError(f"Models folder not found: {MODELS_DIR}")

            print(f"[ML] Loading models from: {MODELS_DIR}")
            _engine = StructuralAnomalyEngine(
                model_dir=str(MODELS_DIR),
                log_file=str(STATIC_DIR / "telemetry_log.csv"),
                dashboard_file=str(STATIC_DIR / "scientific_dashboard.png"),
            )
        except Exception as exc:
            _engine_error = exc
            raise
    return _engine


# ---------------------------------------------------------------
# DB ingestion — returns {node_id: payload} for all fresh nodes
# ---------------------------------------------------------------
def _fetch_payloads_from_db(app):
    from app.models import SensorData

    with app.app_context():
        cutoff = datetime.utcnow() - timedelta(seconds=STALE_DATA_SECONDS)

        fresh_node_ids = [
            row[0] for row in (
                SensorData.query
                .with_entities(SensorData.node_id)
                .filter(SensorData.timestamp >= cutoff)
                .distinct()
                .all()
            )
        ]
        if not fresh_node_ids:
            return {}

        payloads = {}
        for node_id in fresh_node_ids:
            rows = (
                SensorData.query
                .filter(
                    SensorData.node_id == node_id,
                    SensorData.timestamp >= cutoff,
                )
                .order_by(SensorData.timestamp.desc())
                .limit(200)
                .all()
            )
            if not rows:
                continue

            payload = {}
            for r in rows:
                key = _alias(r.sensor_type)
                payload.setdefault(key, float(r.value))

            for src, dst in ML_TRACK_ALIASES.items():
                if src in payload:
                    payload.setdefault(dst, payload[src])

            payloads[node_id] = payload

        return payloads


# ---------------------------------------------------------------
# Simulator (only if DB empty)
# ---------------------------------------------------------------
_sim_step = 0


def _simulate_payload():
    global _sim_step
    _sim_step += 1
    payload = {
        "rotation_x": float(np.random.normal(1.1, 0.1)),
        "rotation_y": float(np.random.normal(5.5, 0.1)),
        "rotation_z": float(np.random.normal(77.7, 0.5)),
        "acceleration_x": float(np.random.normal(0.01, 0.005)),
        "acceleration_y": float(np.random.normal(0.01, 0.005)),
        "acceleration_z": float(np.random.normal(0.06, 0.01)),
        "roof_convergence_cm": float(np.random.normal(300.0, 0.5)),
        "Accel_X (m/s^2)": float(np.random.normal(0.01, 0.005)),
        "Accel_Y (m/s^2)": float(np.random.normal(0.01, 0.005)),
        "Accel_Z (m/s^2)": float(np.random.normal(0.06, 0.01)),
        "Strain (με)": float(np.random.normal(110.0, 0.5)),
        "Temp (°C)":   float(np.random.normal(25.0, 0.2)),
    }
    if _sim_step >= 20:
        payload["roof_convergence_cm"] = 245.0
        payload["rotation_x"] += 15.0
    return payload


# ---------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------
def _persist_result(app, result, node_id):
    from app.models import db, AnalysisLog, Alert, Node

    if not result or result.get("status") != "ACTIVE":
        return

    decision  = result["ultimate_decision"]
    score     = decision["score"]
    text      = decision["status_text"]
    telemetry = result.get("telemetry", {})

    status_map = {0: "normal", 1: "attention", 2: "danger"}
    if score not in status_map:
        return

    with app.app_context():
        node = Node.query.get(node_id)
        if node is None:
            return

        # First mine the node belongs to
        try:
            first_mine = node.mines.first()
        except AttributeError:
            first_mine = node.mines[0] if node.mines else None
        if first_mine is None:
            return
        mine_id = first_mine.id

        # 1. AnalysisLog
        db.session.add(AnalysisLog(
            mine_id=mine_id, node_id=node_id, status=score
        ))

        # 2. Node + Mine status
        node.current_status = status_map[score]
        for m in node.mines:
            m.update_status_from_nodes()

        # 3. Auto alert on danger (throttled)
        if score == 2:
            recent = (Alert.query
                        .filter_by(node_id=node_id, is_automatic=True)
                        .order_by(Alert.timestamp.desc())
                        .first())
            ok = (recent is None
                    or (datetime.utcnow() - recent.timestamp).total_seconds()
                        > ALERT_COOLDOWN_SECS)
            if ok:
                alert_msg = (f"AUTO: {text} detected by AI engine "
                                f"(LSTM={telemetry.get('lstm_mse')}, "
                                f"GRU={telemetry.get('gru_error')})")
                db.session.add(Alert(
                    triggered_by_user_id=None,
                    target_type="node",
                    target_id=node_id,
                    message=alert_msg,
                    is_automatic=True,
                    node_id=node_id,
                    mine_id=mine_id,
                ))
                db.session.commit()
            else:
                db.session.commit()
        else:
            db.session.commit()


# ---------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------
def _background_loop(app):
    try:
        engine = get_engine()
    except Exception as exc:
        print(f"[ML-BG] FATAL: engine failed to load — {exc}")
        return

    while not _stop_flag.is_set():
        try:
            payloads = {}
            if USE_DB_SENSORS:
                payloads = _fetch_payloads_from_db(app)

            if payloads:
                for node_id, payload in payloads.items():
                    result = engine.process_tick(
                        payload,
                        node_id=node_id,
                        auto_render_graph=True,
                    )
                    _persist_result(app, result, node_id)
            elif SIMULATE_IF_EMPTY:
                from app.models import Node
                with app.app_context():
                    fallback = Node.query.first()
                    sim_node_id = fallback.id if fallback else "sim"

                payload = _simulate_payload()
                result = engine.process_tick(
                    payload, node_id=sim_node_id, auto_render_graph=True
                )
                if isinstance(sim_node_id, int):
                    _persist_result(app, result, sim_node_id)

        except Exception as exc:
            print(f"[ML-BG] Tick error: {exc}")

        _stop_flag.wait(TICK_INTERVAL_SECONDS)


def start_background_engine(app):
    """Call from create_app(). Idempotent."""
    global _bg_thread
    if _bg_thread and _bg_thread.is_alive():
        return
    _stop_flag.clear()
    _bg_thread = threading.Thread(
        target=_background_loop,
        args=(app,),
        daemon=True,
        name="ML-Engine-Loop",
    )
    _bg_thread.start()
    print("[ML-BG] Background monitoring thread started")