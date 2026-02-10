
import asyncio
import time
import logging
from backend.services.vision_client import analyze_image
from backend.core.config import settings
import base64

# Configure logging to console
logging.basicConfig(level=logging.INFO)

async def test_vision():
    # Use the image found in the directory
    image_rel_path = "default_thread/dd1e01b38e214739897128f466aed613.jpg"
    image_path = settings.STATIC_DIR / "images" / image_rel_path
    
    print(f"Target image: {image_path}")
    
    if not image_path.exists():
        print(f"Image not found at {image_path}")
        # Try to find any jpg in that folder
        folder = settings.STATIC_DIR / "images" / "default_thread"
        if folder.exists():
            files = list(folder.glob("*.jpg"))
            if files:
                image_path = files[0]
                print(f"Using alternative image: {image_path}")
            else:
                print("No images found to test.")
                return

    with open(image_path, "rb") as f:
        img_bytes = f.read()
    
    # Simulate what ChatInterface sends (Data URL)
    b64 = base64.b64encode(img_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"
    
    print("Sending request to Vision API (Real Image)...")
    start = time.time()
    try:
        # Note: analyze_image reads VISION_MODEL from settings, which we updated in .env
        # We need to make sure settings instance re-reads .env or we monkeypatch it here
        # But settings is loaded at import time. 
        # Ideally, we should restart the process, but for this script we can just proceed 
        # assuming the script interprets .env on launch.
        result = await analyze_image(data_url)
        elapsed = time.time() - start
        print(f"Result: {result}")
        print(f"Time taken: {elapsed:.2f} seconds")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_vision())
