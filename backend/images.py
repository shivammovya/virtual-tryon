"""Shared image helpers: validation, conversion, optional background removal."""
import io
import logging
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024          # 10 MB per image
MAX_SIDE = 1024                       # longest side after resize
ALLOWED_FORMATS = {"JPEG", "PNG"}     # JPG / PNG only


class BadInput(Exception):
    """User-fixable problem (wrong file type, too big...). Becomes HTTP 400."""


def read_image(data: bytes, label: str) -> Image.Image:
    """Validate raw bytes and return a PIL image (still in original mode)."""
    if len(data) > MAX_BYTES:
        raise BadInput(f"The {label} image is larger than 10 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except (UnidentifiedImageError, OSError):
        raise BadInput(f"The {label} file is not a valid image.")
    if fmt not in ALLOWED_FORMATS:
        raise BadInput(f"The {label} image must be a JPG or PNG file.")
    return img


def to_rgb(img: Image.Image) -> Image.Image:
    """Convert to RGB; transparent areas become white."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[3])
        return bg
    return img.convert("RGB")


def save_jpg(img: Image.Image, folder: Path) -> Path:
    """Resize (longest side <= 1024) and save as JPG with a UUID name."""
    img = to_rgb(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    path = folder / f"{uuid.uuid4().hex}.jpg"
    img.save(path, "JPEG", quality=95)
    return path


def save_upload(upload, label: str, folder: Path) -> Path:
    """Validate an UploadFile and save it as a UUID-named JPG."""
    data = upload.file.read(MAX_BYTES + 1)
    return save_jpg(read_image(data, label), folder)


_rembg_session = None  # the model is loaded once, then reused


def person_silhouette(img: Image.Image):
    """Boolean numpy mask of the foreground person (needs rembg), or None if rembg isn't installed.
    Only used by the debug measurements."""
    try:
        from rembg import new_session, remove
        import numpy as np
    except ImportError:
        return None
    global _rembg_session
    if _rembg_session is None:
        _rembg_session = new_session("u2net")
    m = remove(to_rgb(img), session=_rembg_session, only_mask=True)
    return np.asarray(m) > 127


def remove_background(img: Image.Image) -> tuple[Image.Image, bool]:
    """Remove the background with `rembg` if installed.
    Returns (image, removed). If rembg is missing or fails, the image is returned untouched."""
    global _rembg_session
    try:
        from rembg import new_session, remove
    except ImportError:
        return img, False
    try:
        if _rembg_session is None:
            _rembg_session = new_session("u2net")   # use "u2netp" for a smaller/faster, lower-quality model
        small = to_rgb(img)
        small.thumbnail((MAX_SIDE, MAX_SIDE))        # smaller input = far less memory
        return remove(small, session=_rembg_session), True
    except Exception:
        logging.getLogger("images").exception("Background removal failed")
        return img, False
