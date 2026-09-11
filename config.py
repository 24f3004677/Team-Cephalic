
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    #SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://postgres:Sarbanidutta%4012
    SQLALCHEMY_DATABASE_URI = 'sqlite:///cephalic.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_CREATE_DB = True