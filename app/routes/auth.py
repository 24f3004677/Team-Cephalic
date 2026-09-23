from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_

from app import db
from app.models import User
from app.extensions import limiter  

auth_bp = Blueprint('auth', __name__)






@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute") 
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        identifier = (request.form.get('email') or '').strip()
        password   = request.form.get('password') or ''

        # Accept BOTH username and email
        user = User.query.filter(
            or_(User.email == identifier, User.username == identifier)
        ).first()

        if user and user.check_password(password):
            if user.is_blacklisted:
                flash('Your account has been blacklisted. Contact admin.', 'danger')
                return redirect(url_for('auth.login'))

            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))

        flash('Login failed. Check your email/username and password.', 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))