# Website purpose
- to visualise the sensor data from the coal mine
- show status of each node 
- option for creating new node as the coal mine extends
- to send alert to a specific nodes or a group of nodes if there is any emergency --> manual + automatic
- main purpose is to get data from the sensors placed in the coal mine through esp32 board then send it to data processing unit(not the part of website), the processing unit(a custom ml model) will send its analysis and it will be reflected in the website
- eg after getting data from the sensors it was sent to the processing unit then processing unit sends the analysis like {{mine_id:3,node_id:1,status:1},{mine_id:2,node_id:4status:,0},{mine_id:1,node_id:2,status:2}} syntax:{{mine_id,node_id,status}}status:0->under control,1->need attention,2->danger
- each mine can have many nodes ; two mines can have nodes in common;each mine can have many engineers and supervisers
# roles
## admin --> super user
  - can do all the things 
    - creating new node , sending alert , blacklist/unblacklist/remove engineers & superviders
    - create new engineer and superviser
## Engineeres/ supervisers
  - can only login after the admin creates their login credential 
  - can creating new node , sending alert 
  - can see if any their respective mine's gets any error/distress signal from nodes
# website structure

### Web_pages
  - home page(all)
    - Dashboard of number of mines,nodes, engineers/superviser, number of workers inside mines
    - a clickable card for each mine with some info about the mine(mine_name,location,Engineer/superviser,number of workers,status)
    - data of each node is send to processing unit(ml model) which will then provide its analysis and upon that the status of the node and mine will change and the data is sent continuously after 10s
    - if the data sent by the processing unit is danger then the it will instantly send a signal to that node and then the node will start alarming
    - when click on the card then it will show the cards of nodes under that mine, its sensor data and a button for analysis,emergency alarm
    - upon clicking the analysis button the backend will show charts each sensor's data over past data
    - upon clicking the emergency alarm it will send a signal to that node and then the node will start alarming.
    - the sensor data will be first sent to the backend and then it will be sent to the processing unit
  - navbar logo,login/logout,office
  - the office tab will take to a page where admin will have option to create new engineer/superviser,node,mine,job_shift(which mine and its respective engineer , superviser, time shift(day,evening,night))
  - logs option where it will show card for each mine, on clicking on the card it will show which shift has which engineer and superviser

  # tech stack
  - HTML,CSS(Bootstrap)only
  - Python, Flask,jinja2
  - Postgesql

# Models.py file Documentation


---

```python
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
```

- **`from datetime import datetime`**: Imports Python’s `datetime` class so we can use `datetime.utcnow` as default values for timestamp columns.
- **`from flask_sqlalchemy import SQLAlchemy`**: Imports the SQLAlchemy extension for Flask, which provides an ORM (Object Relational Mapper) to interact with the database.
- **`from werkzeug.security import generate_password_hash, check_password_hash`**: Imports utilities for hashing and checking passwords securely. `generate_password_hash` is used when setting a user's password; `check_password_hash` is used during login.

---

```python
db = SQLAlchemy()
```

- **`db = SQLAlchemy()`**: Creates an instance of the SQLAlchemy object. This `db` object is used to define models, create tables, and perform database operations. It will be initialized later in the Flask app factory with `db.init_app(app)`.

---

### Association Tables (Many-to-Many)

```python
mine_nodes = db.Table(
    'mine_nodes',
    db.Column('mine_id', db.Integer, db.ForeignKey('mine.id'), primary_key=True),
    db.Column('node_id', db.Integer, db.ForeignKey('node.id'), primary_key=True)
)
```

- **`mine_nodes = db.Table(...)`**: Defines an association table (not a model class) for the many-to-many relationship between `Mine` and `Node`. 
- **`'mine_nodes'`**: The name of the table in the database.
- **`db.Column('mine_id', db.Integer, db.ForeignKey('mine.id'), primary_key=True)`**: Creates a column `mine_id` that is an integer, a foreign key referencing `mine.id`, and part of the composite primary key.
- **`db.Column('node_id', db.Integer, db.ForeignKey('node.id'), primary_key=True)`**: Similarly for `node_id` referencing `node.id`. This combination ensures that a mine–node pair is unique.

---

```python
user_mines = db.Table(
    'user_mines',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('mine_id', db.Integer, db.ForeignKey('mine.id'), primary_key=True)
)
```

- **`user_mines = db.Table(...)`**: Defines an association table for the many-to-many relationship between `User` (engineers/supervisors) and `Mine`. Each row represents a user being assigned to a mine.
- Columns work exactly like in `mine_nodes`: a composite primary key of `user_id` and `mine_id` ensures no duplicate assignments.

---

### `User` Model

```python
class User(db.Model):
    """User model for admin, engineer, supervisor."""
    __tablename__ = 'user'
```

- **`class User(db.Model)`**: Defines the `User` model, inheriting from `db.Model`. This tells SQLAlchemy to treat this class as a database table.
- **`__tablename__ = 'user'`**: Sets the table name to `user` (default would be `user` anyway, but explicit is clearer).

```python
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'engineer', 'supervisor'
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
```

- **`id`**: Primary key, auto-incrementing integer.
- **`username`**: String column max 80 chars, must be unique and not null. `index=True` creates an index for faster lookups (e.g., during login).
- **`email`**: String max 120 chars, unique and not null.
- **`password_hash`**: String column storing the hashed password (not the plain password). Max length 256 to accommodate the hash.
- **`role`**: String column indicating the user's role. Values are `'admin'`, `'engineer'`, or `'supervisor'`. Not null.
- **`is_blacklisted`**: Boolean flag, defaults to `False`. If set to `True`, the user cannot log in.
- **`created_at`**: DateTime column storing the account creation timestamp. Defaults to current UTC time.

```python
    # Relationships
    mines = db.relationship('Mine', secondary=user_mines, backref=db.backref('users', lazy='dynamic'))
```

- **`mines`**: Defines a many-to-many relationship with `Mine` using the `user_mines` association table. 
  - `secondary=user_mines` points to the association table.
  - `backref=db.backref('users', lazy='dynamic')` creates a reverse relationship on `Mine` called `users`. Because `lazy='dynamic'` is used on the backref, accessing `mine.users` returns a query object that can be further filtered or paginated.

```python
    job_shifts_as_engineer = db.relationship('JobShift', foreign_keys='JobShift.engineer_id', backref='engineer', lazy='dynamic')
    job_shifts_as_supervisor = db.relationship('JobShift', foreign_keys='JobShift.supervisor_id', backref='supervisor', lazy='dynamic')
```

- **`job_shifts_as_engineer`**: One-to-many relationship with `JobShift` where this user is the engineer. 
  - `foreign_keys='JobShift.engineer_id'` explicitly tells SQLAlchemy to use the `engineer_id` foreign key in `JobShift` (since there are two foreign keys to `User` in that table, SQLAlchemy needs clarification).
  - `backref='engineer'` creates a reverse attribute on `JobShift` to access the engineer user.
  - `lazy='dynamic'` returns a query object for the shifts.
- **`job_shifts_as_supervisor`**: Similar, but for the `supervisor_id` foreign key and `supervisor` backref.

```python
    triggered_alerts = db.relationship('Alert', backref='triggered_by_user', lazy='dynamic')
```

- **`triggered_alerts`**: One-to-many relationship with `Alert` where this user manually triggered the alert. 
  - `backref='triggered_by_user'` creates reverse attribute on `Alert` to access the user who triggered it.
  - This relationship only applies to manual alerts; automatic alerts will have `triggered_by_user_id = NULL`.

```python
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
```

- **`set_password(self, password)`**: Convenience method to set the password. It hashes the plain password and stores it in `password_hash`.
- **`check_password(self, password)`**: Checks if the provided plain password matches the stored hash. Returns `True` or `False`.

```python
    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
```

- **`__repr__`**: Returns a readable string representation of the object, useful for debugging.

---

### `Mine` Model

```python
class Mine(db.Model):
    """Represents a coal mine."""
    __tablename__ = 'mine'
```

- Similar declaration as `User`.

```python
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(200))
    workers_count = db.Column(db.Integer, default=0)
    current_status = db.Column(db.String(20), default='normal')  # 'normal', 'attention', 'danger'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
```

- **`id`**: Primary key.
- **`name`**: Unique name of the mine, not null.
- **`location`**: Optional location description.
- **`workers_count`**: Number of workers currently inside the mine. Default 0.
- **`current_status`**: String representing overall mine status: `'normal'`, `'attention'`, or `'danger'`. This is updated based on the status of its nodes. Default `'normal'`.
- **`created_at`**: Timestamp of creation.

```python
    # Relationships
    nodes = db.relationship('Node', secondary=mine_nodes, backref=db.backref('mines', lazy='dynamic'))
```

- **`nodes`**: Many-to-many relationship with `Node` via `mine_nodes`. 
  - `backref='mines'` creates a reverse attribute on `Node` to access all mines it belongs to. `lazy='dynamic'` on the backref means `node.mines` returns a query.

```python
    job_shifts = db.relationship('JobShift', backref='mine', lazy='dynamic')
```

- **`job_shifts`**: One-to-many relationship with `JobShift`. Each job shift belongs to one mine. `backref='mine'` gives `JobShift.mine`.

```python
    analysis_logs = db.relationship('AnalysisLog', backref='mine', lazy='dynamic')
```

- **`analysis_logs`**: One-to-many relationship with `AnalysisLog`. Stores all analysis results for this mine.

```python
    alerts = db.relationship('Alert', backref='mine', lazy='dynamic')
```

- **`alerts`**: One-to-many relationship with `Alert`. Stores alerts targeted at this mine.

```python
    def __repr__(self):
        return f'<Mine {self.name}>'
```

- String representation.

---

### `Node` Model

```python
class Node(db.Model):
    """Represents a sensor node placed inside a mine."""
    __tablename__ = 'node'
```

```python
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    current_status = db.Column(db.String(20), default='normal')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
```

- **`id`**: Primary key.
- **`name`**: Name/identifier of the node, required.
- **`description`**: Optional description.
- **`current_status`**: Latest status from ML analysis: `'normal'`, `'attention'`, or `'danger'`. Default `'normal'`.
- **`created_at`**: Creation timestamp.

```python
    # Relationships
    sensor_data = db.relationship('SensorData', backref='node', lazy='dynamic')
    analysis_logs = db.relationship('AnalysisLog', backref='node', lazy='dynamic')
    alerts = db.relationship('Alert', backref='node', lazy='dynamic')
```

- **`sensor_data`**: One-to-many with raw sensor readings.
- **`analysis_logs`**: One-to-many with analysis results.
- **`alerts`**: One-to-many with alerts targeted to this node.

```python
    def __repr__(self):
        return f'<Node {self.name}>'
```

---

### `SensorData` Model

```python
class SensorData(db.Model):
    """Raw sensor data sent by ESP32 before ML processing."""
    __tablename__ = 'sensor_data'
```

```python
    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.Integer, db.ForeignKey('node.id'), nullable=False)
    sensor_type = db.Column(db.String(50), nullable=False)  # e.g., 'temperature', 'gas', 'humidity'
    value = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
```

- **`id`**: Primary key.
- **`node_id`**: Foreign key to `node.id`, indicating which node sent the data.
- **`sensor_type`**: Type of sensor (e.g., `'temperature'`, `'gas'`, `'humidity'`). Could be expanded to multiple types per node.
- **`value`**: Numeric value read from the sensor.
- **`timestamp`**: When the data was recorded. `index=True` speeds up queries filtered by time.

```python
    def __repr__(self):
        return f'<SensorData {self.sensor_type}={self.value} at {self.timestamp}>'
```

---

### `AnalysisLog` Model

```python
class AnalysisLog(db.Model):
    """Stores the analysis result received from the ML processing unit."""
    __tablename__ = 'analysis_log'
```

```python
    id = db.Column(db.Integer, primary_key=True)
    mine_id = db.Column(db.Integer, db.ForeignKey('mine.id'), nullable=False)
    node_id = db.Column(db.Integer, db.ForeignKey('node.id'), nullable=False)
    status = db.Column(db.Integer, nullable=False)  # 0: under control, 1: need attention, 2: danger
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
```

- **`id`**: Primary key.
- **`mine_id`**: Foreign key to `mine.id` – the mine that contains this node. This is redundant with the node’s mine assignment but helps with quick filtering and aggregation.
- **`node_id`**: Foreign key to `node.id` – the specific node this analysis is about.
- **`status`**: Integer status as provided by the ML model: `0` = under control, `1` = need attention, `2` = danger.
- **`timestamp`**: When the analysis was received/processed.

```python
    def __repr__(self):
        return f'<AnalysisLog mine={self.mine_id} node={self.node_id} status={self.status}>'
```

---

### `Alert` Model

```python
class Alert(db.Model):
    """Logs manual and automatic alerts sent to nodes or groups."""
    __tablename__ = 'alert'
```

```python
    id = db.Column(db.Integer, primary_key=True)
    triggered_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # NULL for automatic
    target_type = db.Column(db.String(20), nullable=False)  # 'node', 'mine', 'group'
    target_id = db.Column(db.Integer, nullable=False)  # ID of node or mine
    message = db.Column(db.String(255))
    is_automatic = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
```

- **`id`**: Primary key.
- **`triggered_by_user_id`**: Foreign key to `user.id`. Nullable, because automatic alerts are not triggered by a specific user.
- **`target_type`**: Indicates what the alert is targeting: `'node'`, `'mine'`, or `'group'`. For group alerts, `target_type='mine'` and `target_id` is the mine ID (since all nodes in that mine are alerted). Could also be `'group'` for ad-hoc groups.
- **`target_id`**: The ID of the target node or mine (or group ID).
- **`message`**: Optional text message to send with the alert.
- **`is_automatic`**: Boolean flag to distinguish automatic alerts (`True`) from manual ones (`False`).
- **`timestamp`**: When the alert was created.

```python
    # Relationships
    mine_id = db.Column(db.Integer, db.ForeignKey('mine.id'), nullable=True)  # optional direct link to mine
    node_id = db.Column(db.Integer, db.ForeignKey('node.id'), nullable=True)  # optional direct link to node
```

- **`mine_id`**, **`node_id`**: Optional direct foreign keys to `Mine` and `Node` for easier querying. They are nullable because the target may be a group or the alert might not be specifically about a single node/mine. The `target_type` and `target_id` could be used instead, but having these direct links simplifies common queries (e.g., “all alerts for mine X”). They are not strictly necessary but convenient.

```python
    def __repr__(self):
        return f'<Alert target={self.target_type}:{self.target_id} automatic={self.is_automatic}>'
```

---

### `JobShift` Model

```python
class JobShift(db.Model):
    """Represents a work shift assignment for a mine."""
    __tablename__ = 'job_shift'
```

```python
    id = db.Column(db.Integer, primary_key=True)
    mine_id = db.Column(db.Integer, db.ForeignKey('mine.id'), nullable=False)
    engineer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    supervisor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    shift_type = db.Column(db.String(20), nullable=False)  # 'day', 'evening', 'night'
    shift_date = db.Column(db.Date, nullable=False)  # The specific date of the shift
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
```

- **`id`**: Primary key.
- **`mine_id`**: Foreign key to `mine.id` – which mine this shift is for.
- **`engineer_id`**: Foreign key to `user.id` – the engineer assigned to this shift.
- **`supervisor_id`**: Foreign key to `user.id` – the supervisor assigned to this shift.
- **`shift_type`**: String indicating shift period: `'day'`, `'evening'`, or `'night'`.
- **`shift_date`**: Date of the shift (without time) for easy filtering by day.
- **`start_time`** and **`end_time`**: Full timestamps indicating when the shift starts and ends.
- **`created_at`**: Record creation timestamp.

```python
    def __repr__(self):
        return f'<JobShift mine={self.mine_id} {self.shift_type} on {self.shift_date}>'
```

---
