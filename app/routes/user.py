from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import Mine, Node, Alert, SensorData, AnalysisLog
from app.utils.decorators import role_required
from datetime import datetime

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
    mines = current_user.mines.all()
    return render_template('create_node.html', mines=mines)
