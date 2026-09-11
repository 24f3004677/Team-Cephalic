"""Live ML telemetry API — polled by the frontend every 2 seconds."""
from flask import Blueprint, jsonify, send_file, current_app, request
from flask_login import login_required
import os
from pathlib import Path

from app.ml_engine import get_engine

api_ml_bp = Blueprint('api_ml', __name__)

_STATIC = Path(__file__).resolve().parents[1] / 'static'
DASHBOARD_PATH = str(_STATIC / 'scientific_dashboard.png')
LOG_CSV_PATH   = str(_STATIC / 'telemetry_log.csv')


@api_ml_bp.route('/live-status')
@login_required
def live_status():
    node_id_param = request.args.get('node_id')
    try:
        node_id = int(node_id_param) if node_id_param else None
    except ValueError:
        node_id = None

    engine = get_engine()

    if node_id is None:
        for nid in engine.node_state.keys():
            node_id = nid
            break

    if node_id is not None:
        hist = engine.get_node_history(node_id)
    else:
        hist = {
            'step': [], 'tilt_x': [], 'roof_dist': [],
            'lstm_mse': [], 'gru_error': [], 'risk_score': [],
        }

    if hist.get('step'):
        latest = {
            'step': hist['step'][-1],
            'tilt_x': round(hist['tilt_x'][-1], 3),
            'roof_convergence': round(hist['roof_dist'][-1], 2),
            'lstm_mse': round(hist['lstm_mse'][-1], 5),
            'gru_error': round(hist['gru_error'][-1], 4),
            'risk_score': hist['risk_score'][-1],
        }
        status_text = {0: "SAFE", 1: "WARNING", 2: "CRITICAL"}.get(
            latest["risk_score"], "UNKNOWN"
        )
    else:
        latest = {}
        status_text = "BUFFERING"

    return jsonify({
        "node_id": node_id,
        "status": status_text,
        "latest": latest,
        "history": {
            "step":       hist['step'][-60:],
            "tilt_x":     hist['tilt_x'][-60:],
            "roof_dist":  hist['roof_dist'][-60:],
            "lstm_mse":   hist['lstm_mse'][-60:],
            "gru_error":  hist['gru_error'][-60:],
            "risk_score": hist['risk_score'][-60:],
        },
    })


@api_ml_bp.route('/dashboard.png')
@login_required
def dashboard_png():
    if not os.path.exists(DASHBOARD_PATH):
        return jsonify({'error': 'no plot yet'}), 404
    return send_file(DASHBOARD_PATH, mimetype='image/png')


@api_ml_bp.route('/telemetry.csv')
@login_required
def telemetry_csv():
    if not os.path.exists(LOG_CSV_PATH):
        return jsonify({'error': 'no log yet'}), 404
    return send_file(LOG_CSV_PATH, mimetype='text/csv',
                     as_attachment=True, download_name='telemetry_log.csv')


@api_ml_bp.route('/simulate', methods=['POST'])
@login_required
def simulate_tick():
    from app.ml_engine import _simulate_payload, _persist_result
    from app.models import Node

    engine = get_engine()
    with current_app.app_context():
        node = Node.query.first()
        node_id = node.id if node else 'sim'

    payload = _simulate_payload()
    result = engine.process_tick(payload, node_id=node_id, auto_render_graph=True)
    if isinstance(node_id, int):
        _persist_result(current_app._get_current_object(), result, node_id)
    return jsonify(result)