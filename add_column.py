import sqlite3
import os

candidates = [
    "instance/cephalic_db",
    "cephalic_db",
    "app/cephalic_db",
    "instance/cephalic_db.sqlite",
]

db_path = None
for p in candidates:
    if os.path.exists(p):
        db_path = p
        print(f"Found DB at: {p}")
        break

if db_path is None:
    print("Could not find the DB file. Checked:", candidates)
    raise SystemExit(1)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

try:
    cur.execute("ALTER TABLE node ADD COLUMN manually_fixed_until DATETIME")
    conn.commit()
    print("✅ Column 'manually_fixed_until' added to 'node' table.")
except sqlite3.OperationalError as e:
    if "duplicate column" in str(e).lower():
        print("ℹ️ Column already exists — nothing to do.")
    else:
        print("❌ Error:", e)

cur.execute("PRAGMA table_info(node)")
cols = [row[1] for row in cur.fetchall()]
print("Columns in 'node' table:")
for c in cols:
    print(" -", c)

conn.close()