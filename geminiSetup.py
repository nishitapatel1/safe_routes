# Checks that your Gemini API key works. Run this first.
#
# One-time setup:
#   1. Get a key at https://aistudio.google.com/app/apikey
#   2. pip install google-genai pillow shapely
#   3. Add this line to your .env file (next to DATABASE_URL):
#        GEMINI_API_KEY=paste-your-key-here
#   4. Never commit .env to GitHub
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("No GEMINI_API_KEY found in .env")

# Model names change often. If you get a "model not found" error,
# open Google AI Studio, copy a current Flash model name, and set
# GEMINI_MODEL in .env (or edit the default below).
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

client = genai.Client(api_key=api_key)

# test 1: plain text
r = client.models.generate_content(model=MODEL, contents="Reply with the single word: ready")
print("text test:", r.text.strip())

# test 2: image (uses test_tile.png from imageryTest.py, if you have it)
if os.path.exists("test_tile.png"):
    with open("test_tile.png", "rb") as f:
        img = types.Part.from_bytes(data=f.read(), mime_type="image/png")
    r = client.models.generate_content(
        model=MODEL,
        contents=[img, "This is an aerial photo. Can you see sidewalks? Answer in one sentence."],
    )
    print("image test:", r.text.strip())
else:
    print("no test_tile.png found, skipping image test")
