from flask import Blueprint, request, jsonify, Response
from app import db
from app.models import Node, SensorData, AnalysisLog, Alert, Mine
from datetime import datetime, timedelta, timezone
import csv
import io

api_bp = Blueprint('api', __name__)

# Endpoint to receive raw sensor data from ESP32
from app import csrf

@csrf.exempt
@api_bp.route('/sensor-data', methods=['POST'])
def receive_sensor_data():
    data = request.get_json()
    if not data or 'node_id' not in data or 'sensor_type' not in data or 'value' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    node_id = data['node_id']
    node = Node.query.get(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404
    sensor_type = data['sensor_type']
    value = float(data['value'])
    timestamp = data.get('timestamp')  # optional, else use current time
    if timestamp:
        try:
            timestamp = datetime.fromisoformat(timestamp)
        except:
            timestamp = datetime.utcnow()
    else:
        timestamp = datetime.utcnow()
    sd = SensorData(node_id=node_id, sensor_type=sensor_type, value=value, timestamp=timestamp)
    db.session.add(sd)
    db.session.commit()
    return jsonify({'success': True, 'id': sd.id}), 201

# Endpoint to receive analysis from ML processing unit
# Expected format: [{"mine_id":1, "node_id":1, "status":2}, ...]
@api_bp.route('/analysis', methods=['POST'])
def receive_analysis():
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({'error': 'Expected a list of analysis objects'}), 400
    for item in data:
        if not all(k in item for k in ('mine_id', 'node_id', 'status')):
            return jsonify({'error': 'Each item must have mine_id, node_id, status'}), 400
        mine_id = item['mine_id']
        node_id = item['node_id']
        status = int(item['status'])
        # Validate existence
        mine = Mine.query.get(mine_id)
        node = Node.query.get(node_id)
        if not mine or not node:
            continue  # skip invalid entries
        # Create analysis log
        log = AnalysisLog(mine_id=mine_id, node_id=node_id, status=status)
        db.session.add(log)
        # Update node current_status
        if status == 0:
            node.current_status = 'normal'
        elif status == 1:
            node.current_status = 'attention'
        elif status == 2:
            node.current_status = 'danger'
        else:
            continue  # invalid status
        # Update mine status based on all its nodes
        # (if any node is danger, mine is danger; else if any attention, attention; else normal)
        mine_nodes = mine.nodes.all()
        statuses = [n.current_status for n in mine.nodes]
        if 'danger' in statuses:
            mine.current_status = 'danger'
        elif 'attention' in statuses:
            mine.current_status = 'attention'
        else:
            mine.current_status = 'normal'
            # Automatic alert if danger
            if status == 2:
                alert = Alert(triggered_by_user_id=None, target_type='node', target_id=node_id,
                              message=f'Automatic danger alert for node {node.name}',
                              is_automatic=True, mine_id=mine_id, node_id=node_id)
                db.session.add(alert)
                
    db.session.commit()
    return jsonify({'success': True, 'processed': len(data)})

# Endpoint to trigger alert to a node (used internally by automatic alerts or external)
@api_bp.route('/trigger-alert', methods=['POST'])
def trigger_alert():
    data = request.get_json()
    if not data or 'target_type' not in data or 'target_id' not in data:
        return jsonify({'error': 'Missing target_type or target_id'}), 400
    target_type = data['target_type']
    target_id = data['target_id']
    message = data.get('message', '')
    is_automatic = data.get('is_automatic', False)

    # Update status based on target
    if target_type == 'node':
        node = Node.query.get(target_id)
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        node.current_status = 'danger'
        for mine in node.mines:
            mine.update_status_from_nodes()
            db.session.add(mine)
        db.session.add(node)
    elif target_type in ('mine', 'group'):
        mine = Mine.query.get(target_id)
        if not mine:
            return jsonify({'error': 'Mine not found'}), 404
        mine.current_status = 'danger'
        for node in mine.nodes:
            node.current_status = 'danger'
            db.session.add(node)
        db.session.add(mine)

    alert = Alert(triggered_by_user_id=None, target_type=target_type, target_id=target_id,
                  message=message, is_automatic=is_automatic)
    db.session.add(alert)
    db.session.commit()
    return jsonify({'success': True, 'alert_id': alert.id}), 201

# ============================================================
# NODE SENSOR DATA — FILTERED VIEW + CSV DOWNLOAD
# ============================================================

# Time-range shortcuts → timedelta
RANGE_MAP = {
    '5m':  timedelta(minutes=5),
    '10m': timedelta(minutes=10),
    '30m': timedelta(minutes=30),
    '1h':  timedelta(hours=1),
    '5h':  timedelta(hours=5),
    '12h': timedelta(hours=12),
    '1d':  timedelta(days=1),
    '5d':  timedelta(days=5),
}


def _parse_range():
    """
    Read ?range=5m|10m|...|custom and optional ?start=...&end=... from query.
    Returns (start_dt, end_dt) as NAIVE UTC datetimes, matching
    the way SensorData.timestamp / AnalysisLog.timestamp are stored.
    """
    range_key = request.args.get('range', '1h')
    start_str = request.args.get('start')
    end_str   = request.args.get('end')

    def _to_naive_utc(s):
        """Parse an ISO string (with or without tz) into a naive UTC datetime."""
        if not s:
            return None
        try:
            # Python 3.11+ handles trailing 'Z' directly, but be safe:
            cleaned = s.strip().replace('Z', '+00:00')
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            return None

        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    # ---- end ----
    end = _to_naive_utc(end_str) or datetime.utcnow()

    # ---- start ----
    if range_key == 'custom':
        start = _to_naive_utc(start_str)
        if start is None:
            # Fallback if custom without valid start
            start = end - timedelta(hours=1)
    else:
        delta = RANGE_MAP.get(range_key, timedelta(hours=1))
        start = end - delta

    # Safety: if start is after end, swap them
    if start > end:
        start, end = end, start

    # Debug: log what we're about to use
    print(f"[API] range={range_key} start={start} end={end}")

    return start, end

@api_bp.route('/node/<int:node_id>/sensor-data', methods=['GET'])
def get_node_sensor_data(node_id):
    """Return sensor readings for a node within the requested time window."""
    node = Node.query.get(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404

    start, end = _parse_range()

    rows = (
        SensorData.query
        .filter(
            SensorData.node_id == node_id,
            SensorData.timestamp >= start,
            SensorData.timestamp <= end,
        )
        .order_by(SensorData.timestamp.asc())
        .all()
    )

    # Group by sensor_type: { sensor_type: [{t, v}, ...] }
    grouped = {}
    for r in rows:
        grouped.setdefault(r.sensor_type, []).append({
            'timestamp':  r.timestamp.isoformat(timespec='seconds') + 'Z',   # explicit UTC marker,
            'value': r.value,
        })

    return jsonify({
        'node_id': node_id,
        'start':   start.isoformat(),
        'end':     end.isoformat(),
        'range':   request.args.get('range', '1h'),
        'count':   len(rows),
        'data':    grouped,
    })


@api_bp.route('/node/<int:node_id>/sensor-data/download', methods=['GET'])
def download_node_sensor_data(node_id):
    """Stream a CSV of the filtered sensor data."""
    node = Node.query.get(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404

    start, end = _parse_range()

    rows = (
        SensorData.query
        .filter(
            SensorData.node_id == node_id,
            SensorData.timestamp >= start,
            SensorData.timestamp <= end,
        )
        .order_by(SensorData.timestamp.asc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'node_id', 'sensor_type', 'value', 'timestamp'])
    for r in rows:
        writer.writerow([r.id, r.node_id, r.sensor_type, r.value,
                         r.timestamp.isoformat()])

    csv_bytes = output.getvalue().encode('utf-8')
    fname = (f'node_{node_id}_sensor_'
             f'{start.strftime("%Y%m%d_%H%M")}_{end.strftime("%Y%m%d_%H%M")}.csv')

    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={fname}'},
    )


@api_bp.route('/node/<int:node_id>/analysis', methods=['GET'])
def get_node_analysis(node_id):
    """Return analysis history for a node within the requested window."""
    node = Node.query.get(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404

    start, end = _parse_range()

    rows = (
        AnalysisLog.query
        .filter(
            AnalysisLog.node_id == node_id,
            AnalysisLog.timestamp >= start,
            AnalysisLog.timestamp <= end,
        )
        .order_by(AnalysisLog.timestamp.desc())
        .all()
    )

    status_text = {0: 'Under Control', 1: 'Need Attention', 2: 'Danger'}

    return jsonify({
        'node_id': node_id,
        'start':   start.isoformat(),
        'end':     end.isoformat(),
        'range':   request.args.get('range', '1h'),
        'count':   len(rows),
        'analysis': [{
            'timestamp':   r.timestamp.isoformat(timespec='seconds') + 'Z',
            'status':      r.status,
            'status_text': status_text.get(r.status, 'Unknown'),
            'mine':        r.mine.name if r.mine else 'N/A',
        } for r in rows],
    })


@api_bp.route('/node/<int:node_id>/analysis/download', methods=['GET'])
def download_node_analysis(node_id):
    """Stream a CSV of the filtered analysis history."""
    node = Node.query.get(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404

    start, end = _parse_range()

    rows = (
        AnalysisLog.query
        .filter(
            AnalysisLog.node_id == node_id,
            AnalysisLog.timestamp >= start,
            AnalysisLog.timestamp <= end,
        )
        .order_by(AnalysisLog.timestamp.asc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'mine_id', 'node_id', 'status', 'status_text', 'timestamp'])
    status_text = {0: 'Under Control', 1: 'Need Attention', 2: 'Danger'}
    for r in rows:
        writer.writerow([r.id, r.mine_id, r.node_id, r.status,
                         status_text.get(r.status, 'Unknown'),
                         r.timestamp.isoformat()])

    csv_bytes = output.getvalue().encode('utf-8')
    fname = (f'node_{node_id}_analysis_'
             f'{start.strftime("%Y%m%d_%H%M")}_{end.strftime("%Y%m%d_%H%M")}.csv')

    return Response(
        csv_bytes,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={fname}'},
    )