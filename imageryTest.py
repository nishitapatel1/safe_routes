import math

import requests



# a spot you know well (your START point works)

lat, lon = 40.9126, -73.1234



# build a box about 130 m wide around it

# longitude degrees shrink as you go north, so divide by cos(latitude) to keep the box square

d_lat = 0.0006

d_lon = d_lat / math.cos(math.radians(lat))

bbox = f"{lon - d_lon},{lat - d_lat},{lon + d_lon},{lat + d_lat}"



# New York State's latest aerial imagery service

url = "https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer/export"

params = {

    "bbox": bbox,

    "bboxSR": 4326,      # our box is in regular lat/lon

    "size": "512,512",   # image size in pixels

    "format": "png",

    "f": "image",        # send back the image itself

}



response = requests.get(url, params=params, timeout=30)

print(response.status_code, response.headers.get("content-type"))



with open("test_tile.png", "wb") as f:

    f.write(response.content)

print("saved test_tile.png")

