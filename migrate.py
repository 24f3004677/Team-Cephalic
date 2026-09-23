import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Load environment variables
load_dotenv()
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not found in .env")

# 2. Create direct engine connection
engine = create_engine(DATABASE_URL)

def column_exists(conn, table_name, column_name):
    """Check if a column exists in a table using information_schema."""
    clean_table = table_name.strip('"').lower()
    query = text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = :table AND column_name = :column
        )
    """)
    result = conn.execute(query, {"table": clean_table, "column": column_name.lower()})
    return result.scalar()

def index_exists(conn, index_name):
    """Check if an index exists using pg_indexes."""
    query = text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_indexes WHERE indexname = :index_name
        )
    """)
    result = conn.execute(query, {"index_name": index_name.lower()})
    return result.scalar()

def run_migration():
    print("Starting PostgreSQL schema migration...")
    
    # engine.begin() ensures all changes commit together, or roll back entirely on error
    with engine.begin() as conn:
        print("1. Adding updated_at columns...")
        tables = ['"user"', 'mine', 'node', 'alert']
        for table in tables:
            if column_exists(conn, table, 'updated_at'):
                print(f"   ℹ️  Skipped: updated_at already exists in {table}")
            else:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP'))
                print(f"   ✅ Added updated_at to {table}")

        print("2. Cleaning up alert.node_id...")
        # Backfill node_id for existing node-specific alerts
        conn.execute(text("""
            UPDATE alert 
            SET node_id = target_id 
            WHERE target_type = 'node' AND node_id IS NULL
        """))
        
        # Delete alerts that target a whole mine or group, because they have no node_id.
        # (Required to satisfy the nullable=False constraint in your models.py)
        result = conn.execute(text("DELETE FROM alert WHERE node_id IS NULL"))
        print(f"   -> Deleted {result.rowcount} alerts that did not belong to a specific node.")
        
        # Add node_id if it doesn't exist yet
        if not column_exists(conn, 'alert', 'node_id'):
            conn.execute(text("ALTER TABLE alert ADD COLUMN node_id INTEGER REFERENCES node(id) ON DELETE CASCADE"))
            print("   ✅ Added node_id to alert")
        
        # Enforce the NOT NULL constraint
        conn.execute(text("ALTER TABLE alert ALTER COLUMN node_id SET NOT NULL"))
        print("   ✅ Enforced NOT NULL on alert.node_id")

        print("3. Updating Foreign Keys for CASCADE deletes...")
        # DROP CONSTRAINT IF EXISTS is safe in PostgreSQL and won't abort the transaction
        conn.execute(text("ALTER TABLE sensor_data DROP CONSTRAINT IF EXISTS sensor_data_node_id_fkey"))
        conn.execute(text("ALTER TABLE sensor_data ADD CONSTRAINT sensor_data_node_id_fkey FOREIGN KEY (node_id) REFERENCES node(id) ON DELETE CASCADE"))
        print("   ✅ Updated sensor_data FK")
        
        conn.execute(text("ALTER TABLE analysis_log DROP CONSTRAINT IF EXISTS analysis_log_node_id_fkey"))
        conn.execute(text("ALTER TABLE analysis_log ADD CONSTRAINT analysis_log_node_id_fkey FOREIGN KEY (node_id) REFERENCES node(id) ON DELETE CASCADE"))
        print("   ✅ Updated analysis_log FK")
        
        conn.execute(text("ALTER TABLE alert DROP CONSTRAINT IF EXISTS alert_node_id_fkey"))
        conn.execute(text("ALTER TABLE alert ADD CONSTRAINT alert_node_id_fkey FOREIGN KEY (node_id) REFERENCES node(id) ON DELETE CASCADE"))
        print("   ✅ Updated alert FK")

        print("4. Creating Indexes...")
        indexes = [
            ("ix_sensor_node_time", "CREATE INDEX ix_sensor_node_time ON sensor_data (node_id, timestamp)"),
            ("ix_analysis_node_time", "CREATE INDEX ix_analysis_node_time ON analysis_log (node_id, timestamp)"),
            ("ix_analysis_mine_time", "CREATE INDEX ix_analysis_mine_time ON analysis_log (mine_id, timestamp)"),
        ]
        for idx_name, sql in indexes:
            if index_exists(conn, idx_name):
                print(f"   ℹ️  Skipped: Index {idx_name} already exists")
            else:
                conn.execute(text(sql))
                print(f"   ✅ Created index {idx_name}")

    print("\n✅ Migration complete!")
    print("You can now safely run `python run.py`.")
    print("The app will start, and db.create_all() will automatically create the new `audit_log` table.")

if __name__ == '__main__':
    run_migration()