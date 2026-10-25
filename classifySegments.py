# Uses Gemini to guess "paved / unpaved / unclear" for path segments
# that have no surface tag in OpenStreetMap. OSM tags always win:
# we only look at segments where the tag is missing.
#
# Run geminiSetup.py first. Start with a small LIMIT and check the crops by hand.
import io
import math
import os
import csv
import time
import requests
import psycopg2
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from shapely import wkt
from google import genai
from google.genai import types

LIMIT = 10            # how many segments to classify this run
PAD = 0.0003          # extra map around each segment, in degrees of latitude (~30 m)
MIN_HALF = 0.0004     # smallest half-height of a crop (~45 m), so short segments aren't too zoomed in
IMG_URL = "https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer/export"
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
ANSWERS = {"paved", "unpaved", "unclear"}

PROMPT = (
    "This is an aerial photo. The segment of path to judge is drawn as a red line. "
    "Is the surface along the red line paved (asphalt, concrete or sidewalk) or unpaved "
    "(dirt, grass or gravel)? If trees, shadows or low quality make it impossible to tell, "
    "say unclear. Answer with exactly one word: paved, unpaved or unclear."
)

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
os.makedirs("crops", exist_ok=True)

# table to remember Gemini's answers (so we never pay for the same segment twice)
cur.execute("""
    CREATE TABLE IF NOT EXISTS gemini_surface (
        id integer PRIMARY KEY,
        answer text
    );
""")
conn.commit()

# segments with no surface tag that Gemini hasn't looked at yet
# (to_postgis saved missing tags as the text 'nan' or 'None')
cur.execute("""
    SELECT e.id, ST_AsText(e.geometry)
    FROM edges e
    LEFT JOIN gemini_surface g ON g.id = e.id
       WHERE (e.surface IS NULL OR e.surface IN ('nan', 'None')) AND g.id IS NULL
    LIMIT %s;
""", (LIMIT,))
todo = cur.fetchall()
print(f"classifying {len(todo)} segments with {MODEL}")


def crop_with_segment(line):
    # get an aerial picture around the segment and draw the segment in red
    minx, miny, maxx, maxy = line.bounds
    lat = (miny + maxy) / 2
    lon = (minx + maxx) / 2
    d_lat = max((maxy - miny) / 2, MIN_HALF) + PAD
    d_lon = max((maxx - minx) / 2, MIN_HALF / math.cos(math.radians(lat))) + PAD / math.cos(math.radians(lat))
    # keep the box square on the ground
    d_lon = max(d_lon, d_lat / math.cos(math.radians(lat)))
    d_lat = d_lon * math.cos(math.radians(lat))
    west, east, south, north = lon - d_lon, lon + d_lon, lat - d_lat, lat + d_lat

    size = 512
    resp = requests.get(IMG_URL, params={
        "bbox": f"{west},{south},{east},{north}", "bboxSR": 4326,
        "size": f"{size},{size}", "format": "png", "f": "image"}, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")

    # lon/lat -> pixel position (y flips: north is the top of the image)
    pts = [((x - west) / (east - west) * size, (north - y) / (north - south) * size)
           for x, y in line.coords]
    ImageDraw.Draw(img).line(pts, fill=(255, 0, 0), width=4)
    return img


rows = []
for seg_id, geom_wkt in todo:
    try:
        img = crop_with_segment(wkt.loads(geom_wkt))
        img.save(f"crops/{seg_id}.png")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        r = client.models.generate_content(
            model=MODEL,
            contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"), PROMPT],
        )
        answer = r.text.strip().lower().strip(".")
        if answer not in ANSWERS:
            answer = "unclear"
    except Exception as e:
        print(f"segment {seg_id} failed: {e}")
        continue
    cur.execute("INSERT INTO gemini_surface (id, answer) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET answer = EXCLUDED.answer;", (seg_id, answer))
    conn.commit()
    rows.append((seg_id, answer))
    print(seg_id, answer)
    time.sleep(0.5)   # be gentle with the rate limit

# save answers next to the crops so you can check them by hand
with open("gemini_results.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["segment_id", "gemini_answer", "correct? (fill in by hand)"])
    w.writerows(rows)

# apply the answers. Only "unpaved" changes the score: raise the penalty
# to 0.8 and block wheelchair routes, the same rule used for tagged dirt paths.
# "paved" and "unclear" leave the score alone.
cur.execute("""
    UPDATE edges e
    SET integrity_penalty = GREATEST(e.integrity_penalty, 0.8),
        wheelchair_blocked = TRUE
    FROM gemini_surface g
      WHERE g.id = e.id AND g.answer = 'unpaved' AND (e.surface IS NULL OR e.surface IN ('nan', 'None'));
""")
conn.commit()

cur.execute("SELECT answer, COUNT(*) FROM gemini_surface GROUP BY answer;")
print("\nall Gemini answers so far:", cur.fetchall())
conn.close()
