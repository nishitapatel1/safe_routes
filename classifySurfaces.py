import os
import io
import math
import time
import requests
import psycopg2
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from shapely import wkt
from google import genai

load_dotenv()

# 1. Connect to Gemini and your Database
API_KEY = "AQ.Ab8RN6L1qXotMHvuTAhTT9Wf0NNMoiR8psvUtVugmHOLbpqdZw"
client = genai.Client(api_key=API_KEY)
conn = psycopg2.connect("postgresql://tsdbadmin:vfjz29cnqf38aklj@j7mlf5985c.gyrzqexx7d.tsdb.cloud.timescale.com:39349/tsdb?sslmode=require")
conn.autocommit = True
cur = conn.cursor()

cur.execute("ALTER TABLE edges ADD COLUMN IF NOT EXISTS gemini_surface TEXT;")

# 2. Grab up to 60 pedestrian paths/footways where surface is missing
cur.execute("""
    SELECT id, highway, ST_AsText(geometry)
    FROM edges
    WHERE (surface = 'nan' OR surface = 'None' OR surface IS NULL)
      AND gemini_surface IS NULL
      AND (highway LIKE '%footway%' OR highway LIKE '%path%' OR highway LIKE '%service%')
    LIMIT 60;
""")
rows = cur.fetchall()
print(f"Found {len(rows)} untagged segments to classify with Gemini...\n")

# Primary NYS URLs + Cloud-friendly High-Res Aerial Fallback (never times out on Codespaces)
IMAGERY_URLS = [
    "https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer/export",
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
]
active_url_idx = 0

def fetch_and_highlight(geom_wkt):
    global active_url_idx
    line = wkt.loads(geom_wkt)
    mid_point = line.interpolate(0.5, normalized=True)
    lon, lat = mid_point.x, mid_point.y

    d_lat = 0.0004
    d_lon = d_lat / math.cos(math.radians(lat))
    min_lon, min_lat = lon - d_lon, lat - d_lat
    max_lon, max_lat = lon + d_lon, lat + d_lat

    params = {
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "bboxSR": 4326,
        "size": "512,512",
        "format": "png",
        "f": "image",
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    # Try current server; if NYS blocks Codespaces IP, switch to fallback automatically
    try:
        resp = requests.get(IMAGERY_URLS[active_url_idx], params=params, headers=headers, timeout=5)
        resp.raise_for_status()
    except Exception:
        if active_url_idx == 0:
            print("⚠️ NYS server blocked Codespaces IP — switching to fast ArcGIS Aerial mirror...")
            active_url_idx = 1
        resp = requests.get(IMAGERY_URLS[active_url_idx], params=params, headers=headers, timeout=15)
        resp.raise_for_status()

    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    draw = ImageDraw.Draw(img)

    pixels = []
    for x, y in line.coords:
        px = (x - min_lon) / (max_lon - min_lon) * 512
        py = (max_lat - y) / (max_lat - min_lat) * 512
        pixels.append((px, py))

    if len(pixels) >= 2:
        draw.line(pixels, fill="cyan", width=4)

    return img

os.makedirs("audit_samples", exist_ok=True)

for idx, (edge_id, highway, geom_wkt) in enumerate(rows):
    try:
        img = fetch_and_highlight(geom_wkt)

        if idx < 30:
            img.save(f"audit_samples/edge_{edge_id}.png")

        prompt = (
            "This is a high-resolution aerial photo of a walkway/road segment highlighted in cyan. "
            "Look closely at the ground surface directly under and immediately alongside the cyan line. "
            "Classify the surface into EXACTLY ONE of these three words: paved, unpaved, or unclear. "
            "Reply with only that single word in lowercase."
        )

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[img, prompt]
        )
        answer = response.text.strip().lower()
        if answer not in ["paved", "unpaved", "unclear"]:
            answer = "unclear"

        if answer == "unpaved":
            new_surface = "unpaved (Gemini)"
            new_penalty = 0.8
            wb = True
        elif answer == "paved":
            new_surface = "paved (Gemini)"
            new_penalty = 0.0 if "path" in highway or "footway" in highway else 0.3
            wb = False
        else:
            new_surface = "unclear (Gemini)"
            new_penalty = 0.3
            wb = False

        cur.execute("""
            UPDATE edges
            SET surface = %s,
                gemini_surface = %s,
                integrity_penalty = GREATEST(integrity_penalty, %s),
                wheelchair_blocked = wheelchair_blocked OR %s
            WHERE id = %s;
        """, (new_surface, answer, new_penalty, wb, edge_id))

        print(f"[{idx+1}/{len(rows)}] Edge {edge_id}: Gemini -> {answer.upper()}")
        time.sleep(1)

    except Exception as e:
        print(f"Error on edge {edge_id}: {e}")

print("\nDone! Check the 'audit_samples' folder to verify 30 images by hand for your pitch.")
conn.close()