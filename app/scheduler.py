# app/scheduler.py
"""
APScheduler wrapper for periodic jobs.
Runs inside the Flask process, in a daemon thread.
"""
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

_scheduler = None


def start_scheduler(app):
    """Idempotent — safe to call more than once."""
    global _scheduler

    if _scheduler and _scheduler.running:
        return

    if not app.config.get('REPORT_ENABLED', True):
        print("[SCHED] Reports disabled via config (REPORT_ENABLED=false).")
        return

    from app.notifications import send_all_reports

    hours = app.config.get('REPORT_INTERVAL_HOURS', 8)

    _scheduler = BackgroundScheduler(daemon=True)

    # Recurring job — every `hours` hours
    _scheduler.add_job(
        func=lambda: send_all_reports(app),
        trigger=IntervalTrigger(hours=hours),
        id='mine_report_recurring',
        name=f'Mine report every {hours}h',
        replace_existing=True,
    )

    