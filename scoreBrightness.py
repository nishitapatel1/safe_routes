# Adds a lighting_penalty column to the edges table, based on the OSM "lit" tag.
#   lit = yes      -> 0.0  (well lit)
#   lit = no       -> 0.8  (dark)
#   no tag at all  -> 0.4  ("we're not sure", bigger than the 0.1 used for surfaces
#                          because most streets have no lit tag, so unknown is common)
#
# IMPORTANT: this matches rows by id. The ids in your database were made by
# scorePaths.py in the order osmnx returned the edges. This script downloads the
# same area with the same settings (osmnx reuses its cached download), so the order
# is the same. If you ever re-run scorePaths.py with a different area or radius,
# re-run this script too.
import os
import osmnx as ox
import psycopg2
from dotenv import load_dotenv

ox.settings.useful_tags_way += ["surface", "footway", "lit"]
G = ox.graph_from_point((40.9126, -73.1234), dist=1500, network_type="walk")
nodes, edges = ox.graph_to_gdfs(G)
edges = edges.reset_index()
edges["id"] = range(1, len(edges) + 1)   # same numbering as scorePaths.py

LIT_YES = {"yes", "24/7", "automatic", "sunset-sunrise"}
LIT_NO = {"no", "disused"}


def lighting_penalty(lit):
    values = lit if isinstance(lit, list) else [lit]
    values = [v for v in values if isinstance(v, str)]   # drops NaN / None
    if not values:
        return 0.4
    if any(v in LIT_NO for v in values):
        return 0.8
    if all(v in LIT_YES for v in values):
        return 0.0
    return 0.4

if "lit" not in edges.columns:
    edges["lit"] = None
edges["lighting_penalty"] = edges["lit"].apply(lighting_penalty)

print("lit tag coverage: %.1f%% of segments" % (edges["lit"].notna().mean() * 100))
print(edges["lighting_penalty"].value_counts().sort_index())

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("ALTER TABLE edges ADD COLUMN IF NOT EXISTS lighting_penalty double precision DEFAULT 0.4;")
cur.executemany("UPDATE edges SET lighting_penalty = %s WHERE id = %s;",
                [(float(p), int(i)) for i, p in zip(edges["id"], edges["lighting_penalty"])])
conn.commit()
cur.execute("SELECT lighting_penalty, COUNT(*) FROM edges GROUP BY 1 ORDER BY 1;")
print("\nin the database:", cur.fetchall())
conn.close()

# map: green = well lit, red = dark. Open brightness_map.html in your browser.
map_data = edges[["geometry", "lighting_penalty", "highway"]].copy()
map_data["highway"] = map_data["highway"].astype(str)
map_data.explore(column="lighting_penalty", cmap="RdYlGn_r", tiles="CartoDB positron",
                 tooltip=["highway", "lighting_penalty"]).save("brightness_map.html")
print("saved brightness_map.html")

# TO USE IT IN ROUTING: in routeTest.py, add this entry to COSTS:
#   "safer": "length * (1 + 2 * integrity_penalty + 2 * lighting_penalty)",
