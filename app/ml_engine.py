"""
ML Engine integration layer.
- Loads StructuralAnomalyEngine once (singleton)
- Runs a background thread that feeds it data (from DB or simulator)
- Saves results to AnalysisLog / Alert / Node status
"""
import os
import threading
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Import your engine
from universal_engine import StructuralAnomalyEngine

# ---------------------------------------------------------------------
# Path resolution
# ml_engine.py lives at:  DL_backend/Team-Cephalic/app/ml_engine.py
#   parents[0] -> DL_backend/Team-Cephalic/app
#   parents[1] -> DL_backend/Team-Cephalic          <-- models lives here
#   parents[2] -> DL_backend
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
SIMULATE_IF_EMPTY     = True
ALERT_COOLDOWN_SECS   = 60

# Map DB/simulator sensor names to the names universal_engine expects.
SENSOR_ALIASES = {
    "accel_x": "Accel_X (m/s^2)",
    "accel_y": "Accel_Y (m/s^2)",
    "accel_z": "Accel_Z (m/s^2)",
    "strain": "Strain (με)",
    "temp": "Temp (°C)",
    "roof_convergence": "roof_convergence_cm",
    "roof_convergence_cm": "roof_convergence_cm",
}


def _alias_sensor_type(sensor_type: str) -> str:
    return SENSOR_ALIASES.get(sensor_type, sensor_type)


# ---------------------------------------------------------------
# Engine singleton
# ---------------------------------------------------------------
def get_engine():
    """Lazy singleton — loads models only once and caches failures."""
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
# Data ingestion
# ---------------------------------------------------------------
def _fetch_sensor_payload_from_db(app):
    """
    Return (node_id, payload) for the most recently active node.
    Returns (None, None) if no fresh sensor data exists.
    """
    from app.models import SensorData

    with app.app_context():
        cutoff = datetime.utcnow() - timedelta(seconds=TICK_INTERVAL_SECONDS * 3)

        latest = (
            SensorData.query
            .filter(SensorData.timestamp >= cutoff)
            .order_by(SensorData.timestamp.desc())
            .first()
        )
        if not latest:
            return None, None

        node_id = latest.node_id

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

        payload = {}
        for row in rows:
            payload.setdefault(_alias_sensor_type(row.sensor_type), row.value)

        # Provide ML-track aliases if only raw axes are present in DB.
        if "acceleration_x" in payload:
            payload.setdefault("Accel_X (m/s^2)", payload["acceleration_x"])
        if "acceleration_y" in payload:
            payload.setdefault("Accel_Y (m/s^2)", payload["acceleration_y"])
        if "acceleration_z" in payload:
            payload.setdefault("Accel_Z (m/s^2)", payload["acceleration_z"])
        if "temperature" in payload:
            payload.setdefault("Temp (°C)", payload["temperature"])

        return node_id, payload


_sim_step = 0


def _simulate_payload():
    """Demo simulator — ramps into CRITICAL after ~20 ticks."""
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

        # ML-track aliases so the statistical detector sees live values too
        "Accel_X (m/s^2)": float(np.random.normal(0.01, 0.005)),
        "Accel_Y (m/s^2)": float(np.random.normal(0.01, 0.005)),
        "Accel_Z (m/s^2)": float(np.random.normal(0.06, 0.01)),
        "Strain (με)":      float(np.random.normal(110.0, 0.5)),
        "Temp (°C)":        float(np.random.normal(25.0, 0.2)),
    }

    if _sim_step >= 20:
        payload["roof_convergence_cm"] = 245.0
        payload["rotation_x"] += 15.0

    return payload


# ---------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------
def _persist_result(app, result, mine_id=None, node_id=None):
    """Write engine output into AnalysisLog, Alert, Node/Mine status."""
    from app.models import db, AnalysisLog, Alert, Node

    if not result or result.get("status") != "ACTIVE":
        return

    decision = result["ultimate_decision"]
    score = decision["score"]
    status_text = decision["status_text"]

    status_map = {0: "normal", 1: "attention", 2: "danger"}
    if score not in status_map:
        return
    node_status_str = status_map[score]

    with app.app_context():
        # Resolve node
        if node_id is None:
            first_node = Node.query.first()
            node_id = first_node.id if first_node else None
        if node_id is None:
            return

        node = Node.query.get(node_id)
        if node is None:
            return

        # Resolve mine from the node's relationships
        if mine_id is None:
            first_mine = (
                node.mines.first()
                if hasattr(node.mines, "first")
                else (node.mines[0] if node.mines else None)
            )
            mine_id = first_mine.id if first_mine else None
        if mine_id is None:
            return

        # 1. AnalysisLog
        db.session.add(AnalysisLog(
            mine_id=mine_id, node_id=node_id, status=score
        ))

        # 2. Update node + mine status
        node.current_status = node_status_str
        for m in node.mines:
            m.update_status_from_nodes()

        # 3. Automatic alert only when entering danger
        if score == 2:
            recent_alert = (
                Alert.query
                .filter_by(node_id=node_id, is_automatic=True)
                .order_by(Alert.timestamp.desc())
                .first()
            )
            cooldown_ok = (
                recent_alert is None
                or (datetime.utcnow() - recent_alert.timestamp).total_seconds()
                   > ALERT_COOLDOWN_SECS
            )
            if cooldown_ok:
                telemetry = result.get("telemetry", {})
                db.session.add(Alert(
                    triggered_by_user_id=None,
                    target_type="node",
                    target_id=node_id,
                    message=(
                        f"AUTO: {status_text} detected by AI engine "
                        f"(LSTM={telemetry.get('lstm_mse')}, "
                        f"GRU={telemetry.get('gru_error')})"
                    ),
                    is_automatic=True,
                    node_id=node_id,
                    mine_id=mine_id,
                ))

        db.session.commit()


# ---------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------
def _background_loop(app):
    # Try to load models once. If it fails, stop the loop cleanly.
    try:
        engine = get_engine()
    except Exception as exc:
        print(f"[ML-BG] FATAL: engine failed to load — background loop not started. {exc}")
        return

    while not _stop_flag.is_set():
        try:
            node_id = None
            payload = None

            if USE_DB_SENSORS:
                node_id, payload = _fetch_sensor_payload_from_db(app)

            if payload is None and SIMULATE_IF_EMPTY:
                payload = _simulate_payload()
                node_id = None

            if payload:
                result = engine.process_tick(payload, auto_render_graph=True)
                _persist_result(app, result, node_id=node_id)

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
    print("[ML-BG] Background monitoring thread started.")