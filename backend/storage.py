"""Product image storage. Supabase Storage when configured (needed on Vercel), otherwise the local folder."""
import io
import uuid
from pathlib import Path

import httpx
from PIL import Image

from . import config
from .images import MAX_SIDE, to_rgb

BUCKET = "product-images"


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": config.SUPABASE_KEY, "Authorization": f"Bearer {config.SUPABASE_KEY}"}
    return {**h, **(extra or {})}


def save_product_image(img: Image.Image) -> str:
    """Resize and store as JPG. Returns the file name (the DB keeps just the name)."""
    img = to_rgb(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    name = f"{uuid.uuid4().hex}.jpg"
    if not config.USE_SUPABASE:
        img.save(config.PRODUCTS_DIR / name, "JPEG", quality=95)
        return name
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    r = httpx.post(f"{config.SUPABASE_URL}/storage/v1/object/{BUCKET}/{name}",
                   headers=_headers({"Content-Type": "image/jpeg"}), content=buf.getvalue(), timeout=60)
    r.raise_for_status()
    return name


def delete_product_image(name: str) -> None:
    if not config.USE_SUPABASE:
        (config.PRODUCTS_DIR / name).unlink(missing_ok=True)
        return
    try:
        httpx.delete(f"{config.SUPABASE_URL}/storage/v1/object/{BUCKET}/{name}", headers=_headers(), timeout=30)
    except httpx.HTTPError:
        pass  # an orphaned image is harmless


def image_url(name: str) -> str:
    if config.USE_SUPABASE:
        return f"{config.SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{name}"
    return f"/product-images/{name}"


def fetch_local(name: str) -> tuple[Path, bool]:
    """A local file path for the image. Returns (path, is_temp); delete it afterwards if is_temp."""
    if not config.USE_SUPABASE:
        return config.PRODUCTS_DIR / name, False
    r = httpx.get(image_url(name), timeout=60)
    r.raise_for_status()
    path = config.UPLOADS_DIR / f"garment_{uuid.uuid4().hex}.jpg"
    path.write_bytes(r.content)
    return path, True
