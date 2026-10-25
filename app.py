import os
import json
import psycopg2
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
app = FastAPI()

# lets the frontend (running on a different port/site) call this API
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# same three modes as routeTest.py
COSTS = {
    "shortest":   "length",
    "walking":    "length * (1 + 2 * integrity_penalty)",
    "wheelchair": "CASE WHEN wheelchair_blocked THEN -1 "
                  "ELSE length * (1 + 2 * integrity_penalty) END",
}

ROUTE_SQL = """
WITH s AS (SELECT osmid FROM nodes
           ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(%(slon)s, %(slat)s), 4326) LIMIT 1),
     t AS (SELECT osmid FROM nodes
           ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(%(elon)s, %(elat)s), 4326) LIMIT 1),
     r AS (SELECT * FROM pgr_dijkstra(%(edges)s, (SELECT osmid FROM s), (SELECT osmid FROM t),
                                      directed := true))
SELECT ST_AsGeoJSON(ST_Collect(e.geometry ORDER BY r.seq)),
       SUM(e.length),
       SUM(e.length * e.integrity_penalty) / NULLIF(SUM(e.length), 0),
       BOOL_OR(e.has_steps)
FROM r JOIN edges e ON e.id = r.edge;
"""


@app.get("/route")
def route(start_lat: float, start_lon: float, end_lat: float, end_lon: float,
          mode: str = "walking"):
    if mode not in COSTS:
        return {"error": f"mode must be one of {list(COSTS)}"}

    edges_sql = f"SELECT id, source, target, {COSTS[mode]} AS cost FROM edges"

    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    try:
        cur = conn.cursor()
        cur.execute(ROUTE_SQL, {"slat": start_lat, "slon": start_lon,
                                "elat": end_lat, "elon": end_lon, "edges": edges_sql})
        geom, meters, avg_penalty, has_steps = cur.fetchone()
    finally:
        conn.close()

    if geom is None:
        return {"error": "no route found"}

    # GeoJSON = the standard format map libraries use to draw shapes
    return {
        "type": "Feature",
        "geometry": json.loads(geom),
        "properties": {
            "mode": mode,
            "meters": round(meters),
            "avg_penalty": round(avg_penalty, 2),
            "has_steps": has_steps,
        },
    }