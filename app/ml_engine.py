"""
ML Engine integration layer.
- Loads StructuralAnomalyEngine once (singleton)
- Runs a background thread that feeds it data (from DB or simulator)
- Saves results to AnalysisLog / Alert / Node status
"""
import os
import time
import threading
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

from universal_engine import StructuralAnomalyEngine

# ------------------------------------------------------------------
# Absolute paths (work no matter where you launch Flask from)
# ml_engine.py lives at:  DL_backend/Team-Cephalic/app/ml_engine.py
# ------------------------------------------------------------------
APP_DIR      = Path(__file__).resolve().parent           # .../Team-Cephalic/app
PROJECT_ROOT = APP_DIR.parents[1]                        # .../DL_backend
MODELS_DIR   = PROJECT_ROOT / 'models'
STATIC_DIR   = APP_DIR / 'static'

STATIC_DIR.mkdir(parents=True, exist_ok=True)

DASHBOARD_PATH = str(STATIC_DIR / 'scientific_dashboard.png')
LOG_CSV_PATH   = str(STATIC_DIR / 'telemetry_log.csv')

# ------------------------------------------------------------------
# Engine state
# ------------------------------------------------------------------
_engine = None
_engine_lock = threading.Lock()
_bg_thread = None
_stop_flag = threading.Event()

TICK_INTERVAL_SECONDS = 2
USE_DB_SENSORS = False        # set True once hardware team feeds the DB
SIMULATE_IF_EMPTY = True


def get_engine():
    """Lazy singleton — loads models only once."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                print(f"[ML] Loading models from: {MODELS_DIR}")
                if not MODELS_DIR.exists():
                    raise RuntimeError(f"Models folder not found: {MODELS_DIR}")
                _engine = StructuralAnomalyEngine(
                    model_dir=str(MODELS_DIR),
                    log_file=LOG_CSV_PATH,
                )
    return _engine


# ------------------------------------------------------------------
# Data ingestion
# ------------------------------------------------------------------
def _fetch_sensor_payload_from_db(app):
    """Read recent SensorData rows (last ~6s). Return dict or None."""
    from app.models import SensorData
    with app.app_context():
        cutoff = datetime.utcnow() - timedelta(seconds=TICK_INTERVAL_SECONDS * 3)
        recent = (SensorData.query
                  .filter(SensorData.timestamp >= cutoff)
                  .order_by(SensorData.timestamp.desc())
                  .limit(200).all())
        if not recent:
            return None
        payload = {}
        for row in recent:
            payload.setdefault(row.sensor_type, row.value)
        return payload


_sim_step = 0


def _simulate_payload():
    """Demo simulator — ramps into CRITICAL after ~20 ticks."""
    global _sim_step
    _sim_step += 1

    payload = {
        'rotation_x': float(np.random.normal(1.1, 0.1)),
        'rotation_y': float(np.random.normal(5.5, 0.1)),
        'rotation_z': float(np.random.normal(77.7, 0.5)),
        'acceleration_x': float(np.random.normal(0.01, 0.005)),
        'acceleration_y': float(np.random.normal(0.01, 0.005)),
        'acceleration_z': float(np.random.normal(0.06, 0.01)),
        'roof_convergence_cm': float(np.random.normal(300.0, 0.5)),
    }
    if _sim_step >= 20:
        payload['roof_convergence_cm'] = 245.0
        payload['rotation_x'] += 15.0
    return payload


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------
def _persist_result(app, result, mine_id=None, node_id=None):
    """Write engine output into AnalysisLog, Alert, Node/Mine status."""
    from app.models import db, AnalysisLog, Alert, Node

    if result.get('status') != 'ACTIVE':
        return

    decision = result['ultimate_decision']
    score = decision['score']
    status_text = decision['status_text']

    status_map = {0: 'normal', 1: 'attention', 2: 'danger'}
    node_status_str = status_map[score]

    with app.app_context():
        if node_id is None:
            first_node = Node.query.first()
            node_id = first_node.id if first_node else None
        if mine_id is None and node_id is not None:
            n = db.session.get(Node, node_id)
            if n and n.mines:
                mine_id = n.mines[0].id

        if node_id is None or mine_id is None:
            return

        log = AnalysisLog(mine_id=mine_id, node_id=node_id, status=score)
        db.session.add(log)

        node = db.session.get(Node, node_id)
        if node:
            node.current_status = node_status_str
            for m in node.mines:
                m.update_status_from_nodes()

        if score == 2:
            recent_alert = (Alert.query
                            .filter_by(node_id=node_id, is_automatic=True)
                            .order_by(Alert.timestamp.desc()).first())
            if (not recent_alert or
                    (datetime.utcnow() - recent_alert.timestamp).total_seconds() > 60):
                alert = Alert(
                    triggered_by_user_id=None,
                    target_type='node',
                    target_id=node_id,
                    message=(f"AUTO: {status_text} detected by AI engine "
                             f"(LSTM={result['telemetry']['lstm_mse']}, "
                             f"GRU={result['telemetry']['gru_error']})"),
                    is_automatic=True,
                    node_id=node_id,
                    mine_id=mine_id,
                )
                db.session.add(alert)

        db.session.commit()


# ------------------------------------------------------------------
# Background loop
# ------------------------------------------------------------------
def _background_loop(app):
    try:
        engine = get_engine()
    except Exception as e:
        print(f"[ML-BG] FATAL: engine failed to load — background loop not started. {e}")
        return

    print("[ML-BG] Loop running. Feeding ticks every "
          f"{TICK_INTERVAL_SECONDS}s ...")

    while not _stop_flag.is_set():
        try:
            payload = None
            if USE_DB_SENSORS:
                payload = _fetch_sensor_payload_from_db(app)
            if payload is None and SIMULATE_IF_EMPTY:
                payload = _simulate_payload()

            if payload:
                result = engine.process_tick(payload, auto_render_graph=True)
                _persist_result(app, result)
        except Exception as e:
            print(f"[ML-BG] Tick error: {e}")
        _stop_flag.wait(TICK_INTERVAL_SECONDS)


def start_background_engine(app):
    """Call this from create_app() — idempotent."""
    global _bg_thread
    if _bg_thread and _bg_thread.is_alive():
        return
    _stop_flag.clear()
    _bg_thread = threading.Thread(
        target=_background_loop, args=(app,),
        daemon=True, name="ML-Engine-Loop"
    )
    _bg_thread.start()
    print("[ML-BG] Background monitoring thread started.")