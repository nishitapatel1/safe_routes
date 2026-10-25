import osmnx as ox

# same setup as before (osmnx cached the download, so this is fast)
ox.settings.useful_tags_way += ["surface", "footway"]
G = ox.graph_from_point((40.9126, -73.1234), dist=1500, network_type="walk")
nodes, edges = ox.graph_to_gdfs(G)

# --- penalty for each path type: 0 = great, 1 = terrible ---
HIGHWAY_PENALTY = {
    "footway": 0.0, "steps": 0.0,                              # steps handled separately
    "path": 0.5,                                               # might be a dirt trail
    "service": 0.3, "residential": 0.3, "unclassified": 0.3,   # walking in the street
    "tertiary": 0.5, "tertiary_link": 0.5, "secondary": 0.6,
    "primary": 0.9, "primary_link": 0.9,
    "trunk": 1.0, "trunk_link": 1.0,                           # busy roads
}

GOOD_SURFACES = {"asphalt", "concrete", "paving_stones", "paved", "concrete:plates"}
ROUGH_SURFACES = {"brick", "bricks", "wood", "unhewn_cobblestone"}
UNPAVED_SURFACES = {"earth", "ground", "dirt", "grass", "gravel"}


def as_list(value):
    # merged segments can hold a list like ['footway', 'steps'],
    # so turn everything into a list to handle both cases the same way
    if isinstance(value, list):
        return value
    if value is None or value != value:  # value != value is True only for NaN (missing)
        return []
    return [value]


def score_edge(highway, surface):
    highways = as_list(highway)
    surfaces = as_list(surface)

    # surface penalty: judge by the worst surface in the segment
    if any(s in UNPAVED_SURFACES for s in surfaces):
        surf_pen = 0.8
    elif any(s in ROUGH_SURFACES for s in surfaces):
        surf_pen = 0.4
    elif surfaces:
        surf_pen = 0.0   # tagged, and all good
    else:
        surf_pen = 0.1   # not tagged = small "we're not sure" penalty

    # path type penalty: a paved "path" is basically a footway, not a trail
    def highway_pen(h):
        if h == "path" and surf_pen == 0.0:
            return 0.0
        return HIGHWAY_PENALTY.get(h, 0.5)  # unknown types get a middle score

    road_pen = max(highway_pen(h) for h in highways)

    return {
        "integrity_penalty": max(road_pen, surf_pen),   # worst thing wins
        "has_steps": "steps" in highways,
        "wheelchair_blocked": "steps" in highways or surf_pen == 0.8,
    }


# run the function on every segment and add the results as new columns
scores = edges.apply(lambda row: score_edge(row["highway"], row.get("surface")),
                     axis=1, result_type="expand")
edges = edges.join(scores)

# --- sanity check the results ---
print("penalty distribution:")
print(edges["integrity_penalty"].value_counts().sort_index())
print("\nwheelchair blocked:")
print(edges["wheelchair_blocked"].value_counts())
# --- draw the scores on an interactive map ---
# keep only the columns we want to see, and turn lists into text so the map can display them
map_data = edges[["geometry", "integrity_penalty", "wheelchair_blocked", "highway", "surface"]].copy()
map_data["highway"] = map_data["highway"].astype(str)
map_data["surface"] = map_data["surface"].astype(str)
map_data = map_data.reset_index(drop=True)

# color every path by penalty: green = good, red = bad
m = map_data.explore(column="integrity_penalty", cmap="RdYlGn_r",
                     tiles="CartoDB positron",
                     tooltip=["highway", "surface", "integrity_penalty"])
# draw wheelchair-blocked segments on top in black so they stand out
map_data[map_data["wheelchair_blocked"]].explore(m=m, color="black")

m.save("integrity_map.html")
print("\nsaved integrity_map.html")

# --- upload to Tiger Data ---
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
# tell SQLAlchemy to use psycopg2 (the driver we installed) instead of its default
db_url = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+psycopg2://", 1)
engine = create_engine(db_url)

# pgRouting needs every segment to have an id, a start point (source) and an end point (target)
db_edges = edges.reset_index()   # moves u, v out of the index into normal columns
db_edges = db_edges.rename(columns={"u": "source", "v": "target"})
db_edges["id"] = range(1, len(db_edges) + 1)

# keep only the columns we need
db_edges = db_edges[["id", "source", "target", "length", "highway", "surface",
                     "integrity_penalty", "has_steps", "wheelchair_blocked", "geometry"]].copy()

# the database can't store python lists in these columns, so turn them into text
db_edges["highway"] = db_edges["highway"].astype(str)
db_edges["surface"] = db_edges["surface"].astype(str)

db_edges.to_postgis("edges", engine, if_exists="replace", index=False)

# nodes = path points. we'll use these to snap a spot the user clicks to the nearest path
db_nodes = nodes.reset_index()[["osmid", "geometry"]]
db_nodes.to_postgis("nodes", engine, if_exists="replace", index=False)

# check that everything made it into the database
with engine.connect() as conn:
    print("\nedges in db:", conn.execute(text("SELECT COUNT(*) FROM edges")).scalar())
    print("nodes in db:", conn.execute(text("SELECT COUNT(*) FROM nodes")).scalar())