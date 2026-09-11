"""Live ML telemetry API — polled by the frontend every 2 seconds."""
from flask import Blueprint, jsonify, send_file, current_app
from flask_login import login_required
import os

from app.ml_engine import get_engine

api_ml_bp = Blueprint('api_ml', __name__)

from pathlib import Path
_STATIC = Path(__file__).resolve().parents[1] / 'static'
DASHBOARD_PATH = str(_STATIC / 'scientific_dashboard.png')
LOG_CSV_PATH   = str(_STATIC / 'telemetry_log.csv')


@api_ml_bp.route('/live-status')
@login_required
def live_status():
    """Returns the engine's full internal state as JSON."""
    engine = get_engine()
    hist = engine.history

    latest = {}
    if hist['step']:
        latest = {
            'step': hist['step'][-1],
            'tilt_x': round(hist['tilt_x'][-1], 3),
            'roof_convergence': round(hist['roof_dist'][-1], 2),
            'lstm_mse': round(hist['lstm_mse'][-1], 5),
            'gru_error': round(hist['gru_error'][-1], 4),
            'risk_score': hist['risk_score'][-1],
        }

    status_text = {0: 'SAFE', 1: 'WARNING', 2: 'CRITICAL'}.get(
        latest.get('risk_score', 0), 'BUFFERING'
    )

    return jsonify({
        'status': status_text,
        'latest': latest,
        'history': {
            'step': hist['step'][-60:],
            'tilt_x': hist['tilt_x'][-60:],
            'roof_dist': hist['roof_dist'][-60:],
            'lstm_mse': hist['lstm_mse'][-60:],
            'gru_error': hist['gru_error'][-60:],
            'risk_score': hist['risk_score'][-60:],
        }
    })


@api_ml_bp.route('/dashboard.png')
@login_required
def dashboard_png():
    """Serves the latest scientific dashboard plot."""
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
    """Manual trigger for demo — injects one simulated tick."""
    from app.ml_engine import _simulate_payload, _persist_result
    engine = get_engine()
    payload = _simulate_payload()
    result = engine.process_tick(payload, auto_render_graph=True)
    _persist_result(current_app._get_current_object(), result)
    return jsonify(result)