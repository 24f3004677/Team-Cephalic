from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import User, Mine, Node
from app.utils.decorators import role_required

admin_bp = Blueprint('admin', __name__)

@admin_bp.before_request
@login_required
@role_required('admin')
def restrict_to_admin():
    pass

@admin_bp.route('/office')
def office():
    users = User.query.all()
    mines = Mine.query.all()
    nodes = Node.query.all()
    return render_template('office.html', users=users, mines=mines, nodes=nodes)

# User management
@admin_bp.route('/user/create', methods=['GET', 'POST'])
def create_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')  # engineer or supervisor
        if role not in ['engineer', 'supervisor']:
            flash('Invalid role', 'danger')
            return redirect(url_for('admin.create_user'))
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'User {username} created successfully', 'success')
        return redirect(url_for('admin.office'))
    return render_template('create_user.html')

@admin_bp.route('/user/<int:user_id>/blacklist', methods=['POST'])
def blacklist_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_blacklisted = not user.is_blacklisted
    db.session.commit()
    status = 'blacklisted' if user.is_blacklisted else 'unblacklisted'
    flash(f'User {user.username} {status}', 'info')
    return redirect(url_for('admin.office'))

@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot delete admin account', 'danger')
        return redirect(url_for('admin.office'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted', 'success')
    return redirect(url_for('admin.office'))

# Mine management
@admin_bp.route('/mine/create', methods=['GET', 'POST'])
def create_mine():
    if request.method == 'POST':
        name = request.form.get('name')
        location = request.form.get('location')
        workers_count = int(request.form.get('workers_count', 0))
        mine = Mine(name=name, location=location, workers_count=workers_count)
        db.session.add(mine)
        db.session.commit()
        flash('Mine created', 'success')
        return redirect(url_for('admin.office'))
    return render_template('create_mine.html')

# Node management
@admin_bp.route('/node/create', methods=['GET', 'POST'])
def create_node():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        mine_ids = request.form.getlist('mines')
        node = Node(name=name, description=description)
        for mid in mine_ids:
            mine = Mine.query.get(int(mid))
            if mine:
                node.mines.append(mine)
        db.session.add(node)
        db.session.commit()
        flash('Node created', 'success')
        return redirect(url_for('admin.office'))
    mines = Mine.query.all()
    return render_template('create_node.html', mines=mines)

# Assign users to mines (engineer/supervisor)
@admin_bp.route('/assign', methods=['POST'])
def assign_user_to_mine():
    user_id = int(request.form.get('user_id'))
    mine_id = int(request.form.get('mine_id'))
    action = request.form.get('action')  # 'assign' or 'remove'
    user = User.query.get_or_404(user_id)
    mine = Mine.query.get_or_404(mine_id)
    if user.role not in ['engineer', 'supervisor']:
        flash('Only engineers and supervisors can be assigned to mines', 'danger')
    else:
        if action == 'assign':
            if mine not in user.mines:
                user.mines.append(mine)
                flash(f'{user.username} assigned to {mine.name}', 'success')
            else:
                flash(f'{user.username} already assigned to {mine.name}', 'info')
        elif action == 'remove':
            if mine in user.mines:
                user.mines.remove(mine)
                flash(f'{user.username} removed from {mine.name}', 'success')
            else:
                flash(f'{user.username} not assigned to {mine.name}', 'info')
        db.session.commit()
    return redirect(url_for('admin.office'))

