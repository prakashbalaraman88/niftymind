"""
Run TimescaleDB setup: enables the extension and converts
time-series tables to hypertables.

Usage:
    python setup_timescaledb.py

Requires DATABASE_URL environment variable.
"""

import os
import sys
import psycopg2

def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set")
        sys.exit(1)

    sql_file = os.path.join(os.path.dirname(__file__), "setup_timescaledb.sql")
    with open(sql_file, "r") as f:
        sql = f.read()

    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cur = conn.cursor()

        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                try:
                    cur.execute(statement)
                    print(f"OK: {statement[:80]}...")
                except Exception as e:
                    print(f"WARN: {statement[:80]}... -> {e}")

        cur.close()
        conn.close()
        print("\nTimescaleDB setup complete.")
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
