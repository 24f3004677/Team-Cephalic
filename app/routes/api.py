from flask import Blueprint, request, jsonify
from app import db
from app.models import Node, SensorData, AnalysisLog, Alert, Mine
from datetime import datetime

api_bp = Blueprint('api', __name__)

# Endpoint to receive raw sensor data from ESP32
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
        statuses = [n.current_status for n in mine_nodes]
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