# app/utils/audit.py
from flask import request
from flask_login import current_user
from app.models import db, AuditLog

def log_audit(action: str, target_type: str = None, target_id: int = None, details: str = None):
    """Helper to record an action in the audit_log table."""
    
    # Safely get user info
    actor_name = "System"
    actor_id = None
    try:
        if current_user and current_user.is_authenticated:
            actor_name = current_user.username
            actor_id = current_user.id
    except RuntimeError:
        pass

    # Safely get the exact host/IP the browser requested
    actor_ip = "Background"
    try:
        if request:
            # request.host captures '127.0.0.2:5001' if that's what was typed
            actor_ip = request.host 
    except RuntimeError:
        pass
    
    # Create the database model instance
    log_entry = AuditLog(
        actor_user_id=actor_id,
        actor_name=actor_name,
        actor_ip=actor_ip,
        action=action.upper(),
        target_type=target_type,
        target_id=target_id,
        details=details
    )
    
    # Add to session (do not commit here, let the route handle it)
    db.session.add(log_entry)