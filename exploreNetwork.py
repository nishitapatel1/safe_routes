import osmnx as ox

# ask osmnx to keep extra tags it normally throws away
# this has to come BEFORE downloading
ox.settings.useful_tags_way += ["surface", "smoothness", "sidewalk", "footway",
                                "incline", "wheelchair", "lit", "step_count"]
ox.settings.useful_tags_node += ["kerb", "crossing"]

center = (40.9126, -73.1234)
G = ox.graph_from_point(center, dist=1500, network_type="walk")
nodes, edges = ox.graph_to_gdfs(G)

print(f"{len(nodes)} nodes, {len(edges)} edges\n")

# check what % of path segments actually have each tag
for tag in ["highway", "surface", "sidewalk", "footway", "incline", "wheelchair", "lit"]:
    if tag in edges.columns:
        pct = edges[tag].notna().mean() * 100
        print(f"{tag:12s} {pct:5.1f}% tagged")
    else:
        print(f"{tag:12s} not present")
# which path types do we have, and how many of each?
print("\nhighway types:")
print(edges["highway"].astype(str).value_counts())

# which surfaces show up? (only the 50% that are tagged)
print("\nsurface values:")
print(edges["surface"].astype(str).value_counts())

# are curb cuts mapped on crossing points?
print("\nkerb values:")
if "kerb" in nodes.columns:
    print(nodes["kerb"].value_counts())
else:
    print("no kerb data")