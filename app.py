import os
import json
import psycopg2
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

load_dotenv()
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

COSTS = {
    "shortest":   "length",
    "walking":    "length * (1 + 2 * integrity_penalty)",
    "wheelchair": "CASE WHEN wheelchair_blocked THEN -1 "
                  "ELSE length * (1 + 2 * integrity_penalty) END",
}

# Added COUNT(*) FILTER (...) to count how many segments in this route Gemini classified
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
       BOOL_OR(e.has_steps),
       COUNT(*) FILTER (WHERE e.surface LIKE '%%Gemini%%')
FROM r JOIN edges e ON e.id = r.edge;
"""

@app.get("/")
def serve_ui():
    # Serves the frontend UI when you visit http://127.0.0.1:8000
    return FileResponse("index.html")

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
        geom, meters, avg_penalty, has_steps, gemini_count = cur.fetchone()
    finally:
        conn.close()

    if geom is None:
        return {"error": "no route found"}

    return {
        "type": "Feature",
        "geometry": json.loads(geom),
        "properties": {
            "mode": mode,
            "meters": round(meters),
            "avg_penalty": round(avg_penalty, 2),
            "has_steps": has_steps,
            "gemini_count": gemini_count or 0,
        },
    }

@app.get("/gemini-segments")
def gemini_segments():
    """Returns all path segments classified by Gemini so the UI can highlight them."""
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, highway, surface, integrity_penalty, ST_AsGeoJSON(geometry)
            FROM edges
            WHERE surface LIKE '%%Gemini%%'
            LIMIT 300;
        """)
        features = []
        for eid, hwy, surf, pen, gj in cur.fetchall():
            features.append({
                "type": "Feature",
                "geometry": json.loads(gj),
                "properties": {"id": eid, "highway": hwy, "surface": surf, "penalty": pen}
            })
        return {"type": "FeatureCollection", "features": features}
    except Exception:
        return {"type": "FeatureCollection", "features": []}
    finally:
        conn.close()