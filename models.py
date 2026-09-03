# database tables of the app 
# importing the required libraries first
from datetime import datetime , time
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.schema import ForeignKey
from flask_login import UserMixin
from sqlalchemy.sql import Nullable

db=SQLAlchemy()

class Staff(UserMixin,db.Model): # admin,engineer,superviser
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')   # admin,engineer,miner
    name = db.Column(db.String(100))
    contact = db.Column(db.String(20))
    gender = db.Column(db.String(10), nullable=True) # Male,Female,Other
    blacklisted = db.Column(db.Boolean, default=False)
	#relationships
	# need to setup
	

class Node(db.Model): # each node
	node_id=db.Column(db.Integer,primary_key=True) #unique node id
	mine_id=db.Column(db.Integer,db.ForeignKey('mine.id'),nullable=True) # unser which mine
	status=db.column(db.string(20),default='Under Control') #Under Control,Need Attension,Danger
	sensor_1=db.column(db.String(100),nullable=True) # sensors data in string need to convert into stuitabe format while processing
	sensor_2=db.column(db.String(100),nullable=True) # only 4 need for prototype
	sensor_3=db.column(db.String(100),nullable=True)
	sensor_4=db.column(db.String(100),nullable=True)
	sensor_5=db.column(db.String(100),nullable=True)
	sensor_6=db.column(db.String(100),nullable=True)
	sensor_7=db.column(db.String(100),nullable=True)
	
class Mine(db.Model):
	mine_id=db.Column(db.Integer,primary_key=True)
	name=db.column(db.string(100))
	location=db.Column(db.string(200),nullable=True)
	distance=db.column(db.Integer(50),nullable=True) # distance from the office
	# if any one of the nodes connected to a mine signals other than Under control
	# the status of the mine will change based on the number of the nodes signalling the error
	# if 1 node then need attention if more than 1 node then danger
	status=db.column(db.string(20),default='Under Control') #Under Control,Need Attension,Danger
	
	
class Job_shit(db.Model):
	id=db.column(db.Integer,primary_key=True)
	mine_id=db.column(db.Integer,db.ForeignKey('mine.id'))
	e_id=db.column(db.Integer,db.ForeignKey('staff.id'))
	
    

