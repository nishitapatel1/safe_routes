import os
import psycopg2
from dotenv import load_dotenv

# load DATABASE_URL from the .env file
load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
conn.autocommit = True  # run each command right away
cur = conn.cursor()

# turn on the map extension (postgis) and the routing extension (pgrouting)
# pgrouting needs postgis, so postgis goes first
cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
cur.execute("CREATE EXTENSION IF NOT EXISTS pgrouting;")

# check that both are working
cur.execute("SELECT postgis_version();")
print("PostGIS:", cur.fetchone()[0])
cur.execute("SELECT pgr_version();")
print("pgRouting:", cur.fetchone()[0])

conn.close()