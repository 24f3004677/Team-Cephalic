import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    #SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://postgres:Sarbanidutta%40123@localhost:5432/cephalic_db'
    SQLALCHEMY_DATABASE_URI ='sqlite:///cephalic_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_CREATE_DB = True

    # Twilio credentials for SMS/WhatsApp alerts
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
    TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER')  # e.g., '+1234567890' or 'whatsapp:+14155238886'