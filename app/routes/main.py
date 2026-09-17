from flask import Blueprint, render_template, redirect, url_for, flash, request, abort,jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Mine, Node, SensorData, AnalysisLog, Alert, User
from app.utils.decorators import role_required

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    total_mines = Mine.query.count()
    total_nodes = Node.query.count()
    total_users = User.query.count()
    total_workers = db.session.query(db.func.sum(Mine.workers_count)).scalar() or 0

    if current_user.role == 'admin':
        mines = Mine.query.order_by(Mine.id.asc()).all()
    else:
        mines = current_user.mines
        

        
    return render_template('dashboard.html',
                           total_mines=total_mines,
                           total_nodes=total_nodes,
                           total_users=total_users-1,
                           total_workers=total_workers,
                           mines=mines)

@main_bp.route('/mine/<int:mine_id>')
@login_required
def mine_detail(mine_id):
    mine = Mine.query.get_or_404(mine_id)
    if current_user.role != 'admin' and mine not in current_user.mines:
        abort(403)
    nodes = sorted(mine.nodes, key=lambda node: node.id)
    return render_template('mine_detail.html', mine=mine, nodes=nodes)

@main_bp.route('/node/<int:node_id>')
@login_required
def node_detail(node_id):
    node = Node.query.get_or_404(node_id)
    if current_user.role != 'admin':
        if not any(mine in current_user.mines for mine in node.mines):
            abort(403)
    sensor_data = {}
    for s in node.sensor_data.order_by(SensorData.timestamp.desc()).limit(200):
        sensor_data.setdefault(s.sensor_type, []).append({
            'timestamp': s.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'value': s.value
        })
    analysis_history = node.analysis_logs.order_by(AnalysisLog.timestamp.desc()).limit(20).all()
    return render_template('node_detail.html', node=node, sensor_data=sensor_data,
                           analysis_history=analysis_history)

@main_bp.route('/logs')
@login_required
def logs():
    if current_user.role == 'admin':
        mines = Mine.query.order_by(Mine.id.asc()).all()
    else:
        mines = current_user.mines
    return render_template('logs.html', mines=mines)


@main_bp.route('/alert/send', methods=['GET', 'POST'])
@login_required
@role_required('engineer', 'supervisor','admin')
def send_alert():
    if request.method == 'POST':
        target_type = request.form.get('target_type')  # 'node' or 'mine'
        message = request.form.get('message')

        if target_type == 'node':
            node_id = request.form.get('node_id')
            if not node_id:
                flash('Please select a node', 'danger')
                return redirect(url_for('user.send_alert'))
            node = Node.query.get_or_404(int(node_id))
            # Check access
            #if not any(mine in current_user.mines for mine in node.mines):
             #   abort(403)
            node.current_status = 'danger'
            db.session.add(node)
            
            # Update all mines containing this node
            for mine in node.mines:
                mine.update_status_from_nodes()
                db.session.add(mine)
            alert = Alert(triggered_by_user_id=current_user.id,
                            target_type='node', target_id=node.id,
                            message=message, is_automatic=False,
                            node_id=node.id
            )
            # NEW:
            try:
                from app.notifications import send_danger_alert
                send_danger_alert(current_app._get_current_object(),
                                    node,
                                    f"MANUAL by {current_user.username}: {message}")
            except Exception as mail_exc:
                print(f"[MAIL] manual alert failed: {mail_exc}")
        elif target_type == 'mine':
            mine_id = request.form.get('mine_id')
            if not mine_id:
                flash('Please select a mine', 'danger')
                return redirect(url_for('user.send_alert'))
            mine = Mine.query.get_or_404(int(mine_id))
            #if mine not in current_user.mines:
            #    abort(403)
            # Set mine and all its nodes to danger
            mine.current_status = 'danger'
            db.session.add(mine)
            for node in mine.nodes:
                node.current_status = 'danger'
                db.session.add(node)
            alert = Alert(triggered_by_user_id=current_user.id,
                            target_type='mine', target_id=mine.id,
                            message=message, is_automatic=False,
                            mine_id=mine.id)
            # NEW: notify once for the mine
            try:
                from app.notifications import send_danger_alert
                from flask import current_app
                # Any node from the mine — we just need one for recipient lookup
                any_node = mine.nodes[0] if mine.nodes else None
                if any_node:
                    send_danger_alert(
                        current_app._get_current_object(),
                        any_node,
                        f"MANUAL by {current_user.username} (whole mine): {message}"
                    )
            except Exception as mail_exc:
                print(f"[MAIL] manual mine alert failed: {mail_exc}")
        else:
            flash('Invalid target type', 'danger')
            return redirect(url_for('main.send_alert'))

        db.session.add(alert)
        db.session.commit()
        flash('Alert sent', 'success')
        return redirect(url_for('main.dashboard'))

    # GET: show form
    if current_user.role == 'admin':
        mines = Mine.query.all()
        nodes = Node.query.all()
    else:
        mines = current_user.mines          # list of Mine objects
        nodes = [node for mine in mines for node in mine.nodes]
    return render_template('send_alert.html', mines=mines, nodes=nodes)

@main_bp.route('/node/<int:node_id>/mark-fixed', methods=['POST'])
@login_required

def mark_node_fixed(node_id):
    node = Node.query.get_or_404(node_id)
    # Access control
    if current_user.role != 'admin':
        if not any(mine in current_user.mines for mine in node.mines):
            abort(403)
    # Mark node as normal with a 5-minute cooldown
    node.current_status = 'normal'
    from datetime import datetime, timedelta
    node.manually_fixed_until = datetime.utcnow() + timedelta(minutes=5)
    db.session.add(node)
    for mine in node.mines:
        mine.update_status_from_nodes()
        db.session.add(mine)
    db.session.commit()
    flash(f'Node {node.name} marked as fixed', 'success')

    next_mine_id = request.form.get('mine_id', type=int)

    if not next_mine_id:
        first_mine = (
            node.mines.first()
            if hasattr(node.mines, "first")
            else (node.mines[0] if node.mines else None)
        )
        next_mine_id = first_mine.id if first_mine else None

    if next_mine_id:
        return redirect(url_for('main.mine_detail', mine_id=next_mine_id))

    return redirect(url_for('main.dashboard'))

@main_bp.route('/mines/map')
@login_required
@role_required('engineer', 'supervisor','admin')
def mines_map():
    # Get mines accessible to current user
    if current_user.role == 'admin':
        mines = Mine.query.all()
    else:
        mines = current_user.mines   # list of Mine objects

    data = []
    for mine in mines:
        if mine.x is not None and mine.y is not None:
            data.append({
                'id': mine.id,
                'name': mine.name,
                'x': mine.x,
                'y': mine.y,
                'status': mine.current_status
            })
    return jsonify(data)