from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import User, Mine, Node, node_links
from app.utils.decorators import role_required


admin_bp = Blueprint('admin', __name__)


@admin_bp.before_request
@login_required
@role_required('admin')
def restrict_to_admin():
    pass


@admin_bp.route('/office')
def office():
    users = User.query.order_by(User.id.asc()).all()
    mines = Mine.query.order_by(Mine.id.asc()).all()
    nodes = Node.query.order_by(Node.id.asc()).all()
    return render_template('office.html', users=users, mines=mines, nodes=nodes)


# =========================================================
# User management
# =========================================================

@admin_bp.route('/user/create', methods=['GET', 'POST'])
def create_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')

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

@admin_bp.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
def edit_user(user_id):
    """Admin-only: edit staff details."""
    user = User.query.get_or_404(user_id)

    # Guard: never let admin edit another admin through this form
    if user.role == 'admin':
        flash('Cannot edit the admin account from here.', 'danger')
        return redirect(url_for('admin.office'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email    = (request.form.get('email') or '').strip()
        phone    = (request.form.get('phone') or '').strip() or None
        role     = request.form.get('role')
        password = (request.form.get('password') or '').strip()

        # ---- Validation ----
        if role not in ('engineer', 'supervisor'):
            flash('Invalid role.', 'danger')
            return redirect(url_for('admin.edit_user', user_id=user.id))

        if not username or not email:
            flash('Username and email are required.', 'danger')
            return redirect(url_for('admin.edit_user', user_id=user.id))

        # Uniqueness checks — exclude the user being edited
        dup_username = User.query.filter(
            User.username == username, User.id != user.id
        ).first()
        if dup_username:
            flash('That username is already taken.', 'danger')
            return redirect(url_for('admin.edit_user', user_id=user.id))

        dup_email = User.query.filter(
            User.email == email, User.id != user.id
        ).first()
        if dup_email:
            flash('That email is already registered.', 'danger')
            return redirect(url_for('admin.edit_user', user_id=user.id))

        # ---- Apply changes ----
        user.username = username
        user.email    = email
        user.phone    = phone
        user.role     = role

        # Only change password if a new one was typed
        if password:
            if len(password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return redirect(url_for('admin.edit_user', user_id=user.id))
            user.set_password(password)

        db.session.commit()
        flash(f'Staff "{user.username}" updated.', 'success')
        return redirect(url_for('admin.office'))

    return render_template('edit_user.html', user=user)

# =========================================================
# Mine management
# =========================================================

@admin_bp.route('/mines/create', methods=['GET', 'POST'])
def create_mine():
    if request.method == 'POST':
        name = request.form.get('name')
        location = request.form.get('location')
        workers_count = request.form.get('workers_count', type=int, default=0)
        x = request.form.get('x', type=float, default=None)
        y = request.form.get('y', type=float, default=None)

        mine = Mine(name=name, location=location,
                    workers_count=workers_count, x=x, y=y)
        db.session.add(mine)
        db.session.commit()
        flash(f'Mine "{name}" created.', 'success')
        return redirect(url_for('admin.list_links'))
    return render_template('create_mine.html')


@admin_bp.route('/mines/<int:mine_id>/edit', methods=['GET', 'POST'])
def edit_mine(mine_id):
    mine = Mine.query.get_or_404(mine_id)
    if request.method == 'POST':
        mine.name = request.form.get('name')
        mine.location = request.form.get('location')
        mine.workers_count = request.form.get('workers_count', type=int, default=0)
        mine.x = request.form.get('x', type=float, default=None)
        mine.y = request.form.get('y', type=float, default=None)
        db.session.commit()
        flash(f'Mine "{mine.name}" updated.', 'success')
        return redirect(url_for('admin.list_links'))
    return render_template('edit_mine.html', mine=mine)


@admin_bp.route('/mines/map')
def mines_map():
    def get_accessible_mines(user):
        if user.role == 'admin':
            return Mine.query.all()
        return user.mines
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


# =========================================================
# Node management
# =========================================================

@admin_bp.route('/nodes/create', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'engineer', 'supervisor')
def create_node():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        mine_ids = request.form.getlist('mines')
        x = request.form.get('x', type=float, default=None)
        y = request.form.get('y', type=float, default=None)

        node = Node(name=name, description=description, x=x, y=y)
        for mid in mine_ids:
            mine = Mine.query.get(int(mid))
            if mine:
                node.mines.append(mine)
        db.session.add(node)
        db.session.commit()
        flash(f'Node "{name}" created.', 'success')
        return redirect(url_for('admin.list_links'))

    mines = Mine.query.order_by(Mine.id.asc()).all() \
        if current_user.role == 'admin' else current_user.mines.all()
    return render_template('create_node.html', mines=mines)


@admin_bp.route('/nodes/<int:node_id>/edit', methods=['GET', 'POST'])
def edit_node(node_id):
    node = Node.query.get_or_404(node_id)
    if request.method == 'POST':
        node.name = request.form.get('name')
        node.description = request.form.get('description')
        node.x = request.form.get('x', type=float, default=None)
        node.y = request.form.get('y', type=float, default=None)

        # Clear existing mine associations
        for m in list(node.mines):
            node.mines.remove(m)

        # Re-attach the selected mines  (FIXED: append inside the loop)
        for mid in request.form.getlist('mines'):
            mine = Mine.query.get(int(mid))
            if mine:
                node.mines.append(mine)

        db.session.commit()
        flash(f'Node "{node.name}" updated.', 'success')
        return redirect(url_for('admin.office'))

    mines = Mine.query.all()
    selected_ids = [mine.id for mine in node.mines]
    return render_template('edit_node.html', node=node,
                           mines=mines, selected_ids=selected_ids)


# =========================================================
# Assign users to mines  (FIXED)
# =========================================================

@admin_bp.route('/assign', methods=['POST'])
def assign_user_to_mine():
    user_id = int(request.form.get('user_id'))
    mine_id = int(request.form.get('mine_id'))
    action = request.form.get('action')  # 'assign' or 'remove'

    # FIXED: removed the invalid .order_by() chain
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


# =========================================================
# Node links — create / list / EDIT / delete
# =========================================================

@admin_bp.route('/links/create', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def create_link():
    if request.method == 'POST':
        from_node_id = request.form.get('from_node_id', type=int)
        to_node_id = request.form.get('to_node_id', type=int)

        if from_node_id == to_node_id:
            flash('Cannot link a node to itself.', 'danger')
            return redirect(url_for('admin.create_link'))

        existing = db.session.query(node_links).filter(
            ((node_links.c.from_node_id == from_node_id) & (node_links.c.to_node_id == to_node_id)) |
            ((node_links.c.from_node_id == to_node_id) & (node_links.c.to_node_id == from_node_id))
        ).first()
        if existing:
            flash('Link already exists between these nodes.', 'warning')
            return redirect(url_for('admin.create_link'))

        stmt = node_links.insert().values(
            from_node_id=from_node_id, to_node_id=to_node_id
        )
        db.session.execute(stmt)
        db.session.commit()
        flash('Link created.', 'success')
        return redirect(url_for('admin.list_links'))

    nodes = Node.query.order_by(Node.name).all()
    return render_template('create_link.html', nodes=nodes)


@admin_bp.route('/links')
@login_required
@role_required('admin')
def list_links():
    links = db.session.query(node_links).all()
    link_list = []
    for link in links:
        from_node = Node.query.get(link.from_node_id)
        to_node = Node.query.get(link.to_node_id)
        link_list.append({'from': from_node, 'to': to_node})
    return render_template('links.html', link_list=link_list)


# -------- NEW: Edit a link -----------------------------------------
@admin_bp.route('/links/<int:from_id>/<int:to_id>/edit',
                methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_link(from_id, to_id):
    """
    Show a form pre-filled with the current (from, to) pair.
    On POST, delete the old link and insert a new one (possibly
    with different endpoints).
    """
    # Load the current link
    link = db.session.query(node_links).filter(
        (node_links.c.from_node_id == from_id) &
        (node_links.c.to_node_id == to_id)
    ).first()

    if link is None:
        flash('Link not found.', 'danger')
        return redirect(url_for('admin.list_links'))

    all_nodes = Node.query.order_by(Node.name).all()

    if request.method == 'POST':
        new_from = request.form.get('from_node_id', type=int)
        new_to = request.form.get('to_node_id', type=int)

        # ---- Validation ----
        if new_from == new_to:
            flash('Cannot link a node to itself.', 'danger')
            return redirect(url_for('admin.edit_link',
                                    from_id=from_id, to_id=to_id))

        if new_from is None or new_to is None:
            flash('Please select both nodes.', 'danger')
            return redirect(url_for('admin.edit_link',
                                    from_id=from_id, to_id=to_id))

        # ---- Check the pair is unique (unless it's identical to the old pair)
        if (new_from, new_to) != (from_id, to_id):
            dup = db.session.query(node_links).filter(
                ((node_links.c.from_node_id == new_from) & (node_links.c.to_node_id == new_to)) |
                ((node_links.c.from_node_id == new_to) & (node_links.c.to_node_id == new_from))
            ).first()
            if dup:
                flash('A link between those nodes already exists.', 'warning')
                return redirect(url_for('admin.edit_link',
                                        from_id=from_id, to_id=to_id))

        # ---- Delete old + insert new (composite PK cannot be UPDATEd directly) ----
        db.session.execute(
            node_links.delete().where(
                (node_links.c.from_node_id == from_id) &
                (node_links.c.to_node_id == to_id)
            )
        )
        db.session.execute(
            node_links.insert().values(
                from_node_id=new_from, to_node_id=new_to
            )
        )
        db.session.commit()
        flash('Link updated.', 'success')
        return redirect(url_for('admin.list_links'))

    return render_template(
        'edit_link.html',
        from_id=from_id,
        to_id=to_id,
        nodes=all_nodes,
    )


# -------- NEW: Delete a link ---------------------------------------
@admin_bp.route('/links/<int:from_id>/<int:to_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_link(from_id, to_id):
    db.session.execute(
        node_links.delete().where(
            (node_links.c.from_node_id == from_id) &
            (node_links.c.to_node_id == to_id)
        )
    )
    db.session.commit()
    flash('Link deleted.', 'success')
    return redirect(url_for('admin.list_links'))

@admin_bp.route('/reports/send-now', methods=['POST'])
@login_required
@role_required('admin')
def send_reports_now():
    from flask import current_app
    from app.notifications import send_all_reports
    send_all_reports(current_app._get_current_object())
    flash('Report run triggered — check your inbox.', 'info')
    return redirect(url_for('admin.office'))