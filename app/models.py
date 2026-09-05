from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()

# Association table for node links (edges)
node_links = db.Table(
    'node_links',
    db.Column('from_node_id', db.Integer, db.ForeignKey('node.id'), primary_key=True),
    db.Column('to_node_id', db.Integer, db.ForeignKey('node.id'), primary_key=True)
)



# Association Tables
mine_nodes = db.Table(
    'mine_nodes',
    db.Column('mine_id', db.Integer, db.ForeignKey('mine.id'), primary_key=True),
    db.Column('node_id', db.Integer, db.ForeignKey('node.id'), primary_key=True)
)

user_mines = db.Table(
    'user_mines',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('mine_id', db.Integer, db.ForeignKey('mine.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    """User model for admin, engineer, supervisor."""
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'engineer', 'supervisor'
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    mines = db.relationship('Mine', secondary=user_mines, backref=db.backref('users', lazy='dynamic'))
    triggered_alerts = db.relationship('Alert', backref='triggered_by_user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

class Mine(db.Model):
    """Represents a coal mine."""
    __tablename__ = 'mine'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(200))
    workers_count = db.Column(db.Integer, default=0)
    current_status = db.Column(db.String(20), default='normal')  # 'normal', 'attention', 'danger'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    x = db.Column(db.Float, nullable=True)   # 0-100 (percentage of container width)
    y = db.Column(db.Float, nullable=True)   # 0-100 (percentage of container height)
    def update_status_from_nodes(self):
        """Recalculate mine status based on the statuses of its nodes."""
        statuses = [node.current_status for node in self.nodes]
        if 'danger' in statuses:
            self.current_status = 'danger'
        elif 'attention' in statuses:
            self.current_status = 'attention'
        else:
           	self.current_status = 'normal'
    # Relationships
    nodes = db.relationship('Node', secondary=mine_nodes, backref=db.backref('mines', lazy='dynamic'))
    analysis_logs = db.relationship('AnalysisLog', backref='mine', lazy='dynamic')
    alerts = db.relationship('Alert', backref='mine', lazy='dynamic')

    def __repr__(self):
        return f'<Mine {self.name}>'

class Node(db.Model):
    """Represents a sensor node placed inside a mine."""
    __tablename__ = 'node'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    current_status = db.Column(db.String(20), default='normal')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    x = db.Column(db.Float, nullable=True)   # 0-100 (percentage of container width)
    y = db.Column(db.Float, nullable=True)   # 0-100 (percentage of container height)
    # Relationships
    sensor_data = db.relationship('SensorData', backref='node', lazy='dynamic')
    analysis_logs = db.relationship('AnalysisLog', backref='node', lazy='dynamic')
    alerts = db.relationship('Alert', backref='node', lazy='dynamic')

    def __repr__(self):
        return f'<Node {self.name}>'

class SensorData(db.Model):
    """Raw sensor data sent by ESP32 before ML processing."""
    __tablename__ = 'sensor_data'

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey('node.id'), nullable=False)
    sensor_type = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f'<SensorData {self.sensor_type}={self.value} at {self.timestamp}>'

class AnalysisLog(db.Model):
    """Stores the analysis result received from the ML processing unit."""
    __tablename__ = 'analysis_log'

    id = db.Column(db.Integer, primary_key=True)
    mine_id = db.Column(db.Integer, db.ForeignKey('mine.id'), nullable=False)
    node_id = db.Column(db.Integer, db.ForeignKey('node.id'), nullable=False)
    status = db.Column(db.Integer, nullable=False)  # 0: under control, 1: need attention, 2: danger
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f'<AnalysisLog mine={self.mine_id} node={self.node_id} status={self.status}>'

class Alert(db.Model):
    """Logs manual and automatic alerts sent to nodes or groups."""
    __tablename__ = 'alert'

    id = db.Column(db.Integer, primary_key=True)
    triggered_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # NULL for automatic
    target_type = db.Column(db.String(20), nullable=False)  # 'node', 'mine', 'group'
    target_id = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(255))
    is_automatic = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Optional direct foreign keys
    mine_id = db.Column(db.Integer, db.ForeignKey('mine.id'), nullable=True)
    node_id = db.Column(db.Integer, db.ForeignKey('node.id'), nullable=True)

    def __repr__(self):
        return f'<Alert target={self.target_type}:{self.target_id} automatic={self.is_automatic}>'