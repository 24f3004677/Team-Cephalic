import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://postgres:Sarbanidutta%40123@localhost:5432/cephalic_db'
    #SQLALCHEMY_DATABASE_URI = 'sqlite:///cephalic.db'

    #SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://postgres:Sarbanidutta%40123@localhost:5432/cephalic_db'
    #SQLALCHEMY_DATABASE_URI= 'sqlite:///cephalic.db'

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_CREATE_DB = True

     # =========================================================
    # EMAIL — SMTP credentials
    # =========================================================
    # =========================================================
    # EMAIL — Yahoo Mail SMTP
    # Sender is fixed; recipients come from User.email in the DB.
    # =========================================================
    MAIL_SERVER   = os.environ.get('MAIL_SERVER', 'smtp.mail.yahoo.com')
    MAIL_PORT     = int(os.environ.get('MAIL_PORT', '587'))
    MAIL_USE_TLS  = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL  = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'

    MAIL_USERNAME       = 'sohamdip_santra@yahoo.com'
    MAIL_DEFAULT_SENDER = 'sohamdip_santra@yahoo.com'

    # Only the app password comes from the environment
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', 'ivfairkbheddvaye')
    #coal_mine_india@yahoo.com
    # sohamdip_santra
    # =========================================================
    # NOTIFICATION / REPORT TOGGLES
    # =========================================================
    NOTIFY_ENABLED        = os.environ.get('NOTIFY_ENABLED', 'true').lower() == 'true'
    REPORT_ENABLED        = os.environ.get('REPORT_ENABLED', 'true').lower() == 'true'
    REPORT_INTERVAL_HOURS = int(os.environ.get('REPORT_INTERVAL_HOURS', '8'))

    # Don't spam the same node's alert more than once per N seconds
    ALERT_EMAIL_COOLDOWN_SECS = int(os.environ.get('ALERT_EMAIL_COOLDOWN_SECS', '300'))

