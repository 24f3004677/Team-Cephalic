# app/notifications.py
"""
Email notification layer for Bhu-Rakshak.

Provides:
  - send_danger_alert(app, node, message)   → fires on node danger
  - send_mine_report(app, mine_id)          → 8-hour summary
  - send_all_reports(app)                   → loops over every mine

All sends run in daemon threads so the caller is never blocked.
All errors are caught and logged — never raised into the ML loop.
"""
import threading
import time
from datetime import datetime, timedelta
from app.models import User
from flask_mail import Mail, Message
from flask import render_template_string

# Flask-Mail singleton — init_app() is called from create_app()
mail = Mail()

# In-process cooldown so we don't spam the same node's alert
_recent_alerts = {}     # {node_id: unix_timestamp}


# =========================================================
# EMAIL TEMPLATES (inline — self-contained)
# =========================================================

ALERT_HTML = """
<!DOCTYPE html>
<html><body style="font-family:Inter,Arial,sans-serif;background:#f5f7fb;padding:24px;">
<div style="max-width:640px;margin:auto;background:#fff;border-radius:14px;
            box-shadow:0 8px 24px rgba(30,60,120,0.08);overflow:hidden;">

  <div style="background:linear-gradient(135deg,#7f1d1d,#dc2626);color:#fff;
              padding:22px 26px;">
    <h1 style="margin:0;font-size:20px;">⚠️ DANGER ALERT</h1>
    <div style="opacity:.9;font-size:12px;margin-top:4px;">
      Bhu-Rakshak · Intelligent Mine Safety
    </div>
  </div>

  <div style="padding:24px 26px;color:#16283c;">
    <h2 style="margin-top:0;font-size:17px;">
      Node: {{ node.name }} <span style="color:#64748b;">(ID {{ node.id }})</span>
    </h2>

    <table style="width:100%;font-size:13px;border-collapse:collapse;">
      <tr><td style="padding:6px 0;color:#64748b;">Mine</td>
          <td style="padding:6px 0;"><b>{{ mine_name }}</b></td></tr>
      <tr><td style="padding:6px 0;color:#64748b;">Status</td>
          <td style="padding:6px 0;">
            <span style="background:#fee2e2;color:#991b1b;
                         padding:3px 10px;border-radius:999px;font-size:12px;">
              {{ node.current_status|upper }}
            </span>
          </td></tr>
      <tr><td style="padding:6px 0;color:#64748b;">Detected</td>
          <td style="padding:6px 0;">{{ timestamp }}</td></tr>
    </table>

    <div style="margin-top:18px;padding:14px;background:#fef2f2;
                border:1px solid #fecaca;border-radius:10px;
                font-size:13px;color:#7f1d1d;line-height:1.6;">
      <b>Message:</b><br>{{ message }}
    </div>

    <p style="color:#64748b;font-size:12px;margin-top:22px;">
      Please review the node in the Bhu-Rakshak dashboard.
    </p>
  </div>
</div>
</body></html>
"""


REPORT_HTML = """
<!DOCTYPE html>
<html><body style="font-family:Inter,Arial,sans-serif;background:#f5f7fb;padding:24px;">
<div style="max-width:760px;margin:auto;background:#fff;border-radius:14px;
            box-shadow:0 8px 24px rgba(30,60,120,0.08);overflow:hidden;">

  <div style="background:linear-gradient(135deg,#0b2b3f,#1a4b62);color:#fff;
              padding:22px 26px;">
    <h1 style="margin:0;font-size:20px;">Bhu-Rakshak — {{ hours }}-Hour Report</h1>
    <div style="opacity:.85;font-size:12px;margin-top:4px;">
      Window: {{ start.strftime('%Y-%m-%d %H:%M') }} → {{ end.strftime('%Y-%m-%d %H:%M') }} UTC
    </div>
  </div>

  <div style="padding:24px 26px;color:#16283c;">
    <h2 style="margin-top:0;font-size:17px;">Mine: {{ mine.name }}</h2>
    <div style="color:#64748b;font-size:13px;margin-bottom:18px;">
      Location: {{ mine.location or 'Not specified' }} ·
      Workers: {{ mine.workers_count }} ·
      Overall status: {{ mine.current_status }}
    </div>

    <table style="width:100%;border-collapse:separate;border-spacing:8px 0;">
      <tr>
        <td style="padding:12px;background:#f1f5fb;border-radius:10px;text-align:center;">
          <div style="font-size:22px;font-weight:700;">{{ nodes_total }}</div>
          <div style="font-size:11px;color:#64748b;">NODES</div>
        </td>
        <td style="padding:12px;background:#e8f7ef;border-radius:10px;text-align:center;">
          <div style="font-size:22px;font-weight:700;color:#059669;">{{ normal_count }}</div>
          <div style="font-size:11px;color:#64748b;">NORMAL</div>
        </td>
        <td style="padding:12px;background:#fff7e6;border-radius:10px;text-align:center;">
          <div style="font-size:22px;font-weight:700;color:#d97706;">{{ attention_count }}</div>
          <div style="font-size:11px;color:#64748b;">ATTENTION</div>
        </td>
        <td style="padding:12px;background:#fdeaea;border-radius:10px;text-align:center;">
          <div style="font-size:22px;font-weight:700;color:#dc2626;">{{ danger_count }}</div>
          <div style="font-size:11px;color:#64748b;">DANGER</div>
        </td>
      </tr>
    </table>

    <h3 style="font-size:14px;margin-top:26px;">Danger Events (this window)</h3>
    {% if alerts %}
      <table style="width:100%;font-size:13px;border-collapse:collapse;">
        <tr style="background:#f8fafc;text-align:left;">
          <th style="padding:8px;border-bottom:1px solid #e2e8f0;">Time (UTC)</th>
          <th style="padding:8px;border-bottom:1px solid #e2e8f0;">Message</th>
        </tr>
        {% for a in alerts %}
        <tr>
          <td style="padding:8px;border-bottom:1px solid #f1f5f9;white-space:nowrap;">
            {{ a.timestamp.strftime('%Y-%m-%d %H:%M') }}
          </td>
          <td style="padding:8px;border-bottom:1px solid #f1f5f9;">
            {{ a.message or 'Danger alert' }}
          </td>
        </tr>
        {% endfor %}
      </table>
    {% else %}
      <p style="color:#64748b;font-size:13px;">
        No danger alerts fired during this window.
      </p>
    {% endif %}

    <p style="color:#94a3b8;font-size:11px;margin-top:26px;">
      Automated report from Bhu-Rakshak. Do not reply.
    </p>
  </div>
</div>
</body></html>
"""


# =========================================================
# RECIPIENT RESOLUTION
# =========================================================

def _resolve_recipients(mine_id=None):
    from app.models import User, Mine
    emails = set()

    # 1. Every admin user
    for admin in User.query.filter_by(role='admin').all():
        if admin.email:
            emails.add(admin.email.strip())

    # 2. Engineers + supervisors of the specific mine
    if mine_id is not None:
        mine = Mine.query.get(mine_id)
        if mine:
            for u in mine.users:
                if u.role in ('engineer', 'supervisor') and u.email:
                    emails.add(u.email.strip())

    return sorted(emails)


# =========================================================
# LOW-LEVEL SENDER (runs in a background thread)
# =========================================================

def _send_thread(app, recipients, subject, html_body):
    """Actual SMTP send — runs on a daemon thread with its own app context."""
    with app.app_context():

        sender = app.config.get('MAIL_USERNAME')

        if not sender:
            print("[MAIL] ERROR: MAIL_USERNAME is not set. "
                  "Add it to .env or the environment. Email NOT sent.")
            return

        try:
            msg = Message(
                subject=subject,
                recipients=recipients,
                html=html_body,
                sender=sender,
            )
            mail.send(msg)
            print(f"[MAIL] Sent '{subject}' → {len(recipients)} recipient(s) as {sender}")
        except Exception as e:
            print(f"[MAIL] Failed to send '{subject}': {e}")
            print(f"[MAIL] Debug: MAIL_SERVER={app.config.get('MAIL_SERVER')}")
            print(f"[MAIL] Debug: MAIL_PORT={app.config.get('MAIL_PORT')}")
            print(f"[MAIL] Debug: MAIL_USE_TLS={app.config.get('MAIL_USE_TLS')}")
            print(f"[MAIL] Debug: MAIL_USERNAME={sender}")
            print(f"[MAIL] Debug: PASSWORD SET={'yes' if app.config.get('MAIL_PASSWORD') else 'NO'}")


def _dispatch_async(app, recipients, subject, html_body):
    """Queue an email for background delivery."""
    if not app.config.get('NOTIFY_ENABLED', True):
        print(f"[MAIL] Skipped (NOTIFY_ENABLED=false): {subject}")
        return
    if not recipients:
        print(f"[MAIL] Skipped (no recipients): {subject}")
        return
    t = threading.Thread(
        target=_send_thread,
        args=(app, recipients, subject, html_body),
        daemon=True,
        name="Mail-Async",
    )
    t.start()


# =========================================================
# PUBLIC API
# =========================================================

def send_danger_alert(app, node, message):
    """
    Fire an alert email about a node hitting danger.
    Honours ALERT_EMAIL_COOLDOWN_SECS so repeated ticks don't spam inboxes.
    """
    if not app.config.get('NOTIFY_ENABLED', True):
        return

    now = time.time()
    cooldown = app.config.get('ALERT_EMAIL_COOLDOWN_SECS', 60)
    last = _recent_alerts.get(node.id)
    if last and (now - last) < cooldown:
        print(f"[MAIL] Node {node.id} alert suppressed (cooldown {cooldown}s).")
        return
    _recent_alerts[node.id] = now

    # Determine the mine (first one) for recipient lookup
    mine_id = None
    mine_name = 'Unassigned'
    try:
        first_mine = (node.mines.first()
                      if hasattr(node.mines, 'first')
                      else (node.mines[0] if node.mines else None))
        if first_mine:
            mine_id = first_mine.id
            mine_name = first_mine.name
    except Exception:
        pass

    recipients = _resolve_recipients(mine_id)
    if not recipients:
        print(f"[MAIL] No email recipients configured for mine {mine_id}.")
        return

    html = render_template_string(
        ALERT_HTML,
        node=node,
        mine_name=mine_name,
        message=message,
        timestamp=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
    )

    subject = (f"[Bhu-Rakshak] DANGER — {node.name} "
               f"({mine_name})")

    _dispatch_async(app, recipients, subject, html)


def send_mine_report(app, mine_id):
    """Build and send the 8-hour report for one mine."""
    from app.models import Mine, Alert

    if not app.config.get('REPORT_ENABLED', True):
        return

    mine = Mine.query.get(mine_id)
    if mine is None:
        print(f"[MAIL] Mine {mine_id} not found.")
        return

    recipients = _resolve_recipients(mine_id)
    if not recipients:
        print(f"[MAIL] No recipients for mine {mine_id}.")
        return

    hours = app.config.get('REPORT_INTERVAL_HOURS', 8)
    end   = datetime.utcnow()
    start = end - timedelta(hours=hours)

    nodes = list(mine.nodes)
    nodes_total     = len(nodes)
    normal_count    = sum(1 for n in nodes if n.current_status == 'normal')
    attention_count = sum(1 for n in nodes if n.current_status == 'attention')
    danger_count    = sum(1 for n in nodes if n.current_status == 'danger')

    alerts = (Alert.query
              .filter(Alert.mine_id == mine.id,
                      Alert.timestamp >= start,
                      Alert.timestamp <= end)
              .order_by(Alert.timestamp.desc())
              .limit(30)
              .all())

    html = render_template_string(
        REPORT_HTML,
        hours=hours,
        start=start,
        end=end,
        mine=mine,
        nodes_total=nodes_total,
        normal_count=normal_count,
        attention_count=attention_count,
        danger_count=danger_count,
        alerts=alerts,
    )

    subject = (f"[Bhu-Rakshak] {hours}-hr report — {mine.name} "
               f"({danger_count} danger)")

    _dispatch_async(app, recipients, subject, html)


def send_all_reports(app):
    """Loop over every mine and send its 8-hour report."""
    from app.models import Mine

    with app.app_context():
        mine_ids = [m.id for m in Mine.query.order_by(Mine.id.asc()).all()]

    print(f"[MAIL] Starting {app.config.get('REPORT_INTERVAL_HOURS', 8)}-hr report run — {len(mine_ids)} mine(s).")
    for mid in mine_ids:
        try:
            send_mine_report(app, mid)
        except Exception as e:
            print(f"[MAIL] Report failed for mine {mid}: {e}")

def send_reports_for_mines(app, mine_ids, recipient_emails, hours=None):
    """
    Send one report per mine in `mine_ids` to the explicit list
    `recipient_emails`. Used by the admin "Send Report" page.

    Unlike send_all_reports(), this does NOT resolve recipients from
    the DB — the caller passes the exact list they want.
    """
    from app.models import Mine, Alert

    if not app.config.get('NOTIFY_ENABLED', True):
        print("[MAIL] Skipped — NOTIFY_ENABLED=false")
        return

    if not mine_ids:
        print("[MAIL] No mines selected.")
        return

    if not recipient_emails:
        print("[MAIL] No recipients selected.")
        return

    hours = hours or app.config.get('REPORT_INTERVAL_HOURS', 8)

    for mid in mine_ids:
        try:
            mine = Mine.query.get(mid)
            if mine is None:
                print(f"[MAIL] Mine {mid} not found — skipping.")
                continue

            end   = datetime.utcnow()
            start = end - timedelta(hours=hours)

            nodes = list(mine.nodes)
            nodes_total     = len(nodes)
            normal_count    = sum(1 for n in nodes if n.current_status == 'normal')
            attention_count = sum(1 for n in nodes if n.current_status == 'attention')
            danger_count    = sum(1 for n in nodes if n.current_status == 'danger')

            alerts = (Alert.query
                      .filter(Alert.mine_id == mine.id,
                              Alert.timestamp >= start,
                              Alert.timestamp <= end)
                      .order_by(Alert.timestamp.desc())
                      .limit(30)
                      .all())

            html = render_template_string(
                REPORT_HTML,
                hours=hours,
                start=start,
                end=end,
                mine=mine,
                nodes_total=nodes_total,
                normal_count=normal_count,
                attention_count=attention_count,
                danger_count=danger_count,
                alerts=alerts,
            )

            subject = (f"[Bhu-Rakshak] {hours}-hr report — {mine.name} "
                       f"({danger_count} danger)")

            _dispatch_async(app, recipient_emails, subject, html)

        except Exception as e:
            print(f"[MAIL] Report failed for mine {mid}: {e}")

    print(f"[MAIL] Manual report run queued — "
          f"{len(mine_ids)} mine(s), {len(recipient_emails)} recipient(s).")