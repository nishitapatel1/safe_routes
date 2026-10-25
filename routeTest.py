import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

# paste your two points here (latitude, longitude)
START = (40.919929279192196, -73.12845828628686)
END = (40.91588846611973, -73.12580717945043)


def nearest_node(lat, lon):
    # find the path point closest to a spot. <-> is postgis's fast "distance to" operator
    cur.execute("""
        SELECT osmid FROM nodes
        ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1;
    """, (lon, lat))  # careful: postgis wants (lon, lat), the opposite of google maps
    return cur.fetchone()[0]


# how much each segment "costs" in each mode
# -1 tells pgRouting the segment doesn't exist (blocked)
COSTS = {
    "shortest":   "length",
    "walking":    "length * (1 + 2 * integrity_penalty)",
    "wheelchair": "CASE WHEN wheelchair_blocked THEN -1 "
                  "ELSE length * (1 + 2 * integrity_penalty) END",
}


def route(start, end, cost_expr):
    # pgRouting wants a query that returns id, source, target, cost for every segment
    edges_sql = f"SELECT id, source, target, {cost_expr} AS cost FROM edges"

    # run dijkstra (cheapest path), then join back to edges to summarize the route
    cur.execute("""
        SELECT COUNT(*),
               SUM(e.length),
               SUM(e.length * e.integrity_penalty) / NULLIF(SUM(e.length), 0),
               BOOL_OR(e.has_steps)
        FROM pgr_dijkstra(%s, %s, %s, directed := true) AS r
        JOIN edges e ON e.id = r.edge;
    """, (edges_sql, start, end))
    return cur.fetchone()


start_node = nearest_node(*START)
end_node = nearest_node(*END)
print("start node:", start_node, "| end node:", end_node, "\n")

for mode, expr in COSTS.items():
    segments, meters, avg_penalty, has_steps = route(start_node, end_node, expr)
    if segments == 0:
        print(f"{mode:10s} no route found")
        continue
    print(f"{mode:10s} {meters:6.0f} m | avg penalty {avg_penalty:.2f} | steps: {has_steps}")

conn.close()