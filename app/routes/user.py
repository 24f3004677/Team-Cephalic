from flask import Blueprint, render_template, redirect, url_for, flash, request, abort,jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Mine, Node, Alert, SensorData, AnalysisLog
from app.utils.decorators import role_required
from datetime import datetime
from app.models import node_links


def has_mine_access(user, mine_id):
    if user.role == 'admin':
        return True
    return any(mine.id == mine_id for mine in user.mines)

def get_accessible_mines(user):
    if user.role == 'admin':
        return Mine.query.all()
    return user.mines
    
user_bp = Blueprint('user', __name__)

@user_bp.before_request
@login_required
@role_required('engineer', 'supervisor',"admin")
def restrict_to_engineer_supervisor():
    pass

# Create node (engineers/supervisors can create nodes for mines they are assigned to)
@user_bp.route('/node/create', methods=['GET', 'POST'])
def create_node():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        mine_ids = request.form.getlist('mines')
        node = Node(name=name, description=description)
        # Ensure they only assign to mines they have access to
        for mid in mine_ids:
            mine = Mine.query.get(int(mid))
            if mine and mine in current_user.mines:
                node.mines.append(mine)
        db.session.add(node)
        db.session.commit()
        flash('Node created', 'success')
        return redirect(url_for('main.dashboard'))
    # Only show mines assigned to current user
    mines = current_user.mines
    return render_template('create_node.html', mines=mines)

@user_bp.route('/mine/<int:mine_id>/graph')
@login_required
@role_required('engineer', 'supervisor',"admin")
def mine_graph(mine_id):
    mine = Mine.query.get_or_404(mine_id)
    if not has_mine_access(current_user, mine_id):
        abort(403)

    nodes = mine.nodes  # directly iterate, no .all()
    node_data = []
    for node in nodes:
        latest_analysis = AnalysisLog.query.filter_by(node_id=node.id).order_by(AnalysisLog.timestamp.desc()).first()
        status = latest_analysis.status if latest_analysis else None
        status_str = 'normal' if status == 0 else 'attention' if status == 1 else 'danger' if status == 2 else 'unknown'
        node_data.append({
            'id': node.id,
            'name': node.name,
            'x': node.x,
            'y': node.y,
            'status': status_str
        })

    node_ids = [n['id'] for n in node_data]
    links = []
    if node_ids:
        # Since both endpoints must be in this mine, a single query is enough
        result = db.session.query(node_links).filter(
            node_links.c.from_node_id.in_(node_ids),
            node_links.c.to_node_id.in_(node_ids)
        ).all()
        for link in result:
            links.append({'from': link.from_node_id, 'to': link.to_node_id})

    return jsonify({'nodes': node_data, 'links': links})


@user_bp.route('/mines/map')
@login_required   # all authenticated users can access
@role_required('engineer', 'supervisor',"admin")
def mines_map():
    mines = get_accessible_mines(current_user)
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