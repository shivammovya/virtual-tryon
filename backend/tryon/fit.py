"""Image geometry helpers for try-on: pad to 3:4 instead of stretching, mask tools, compositing.

Pure PIL + numpy (no model, no network) so it can be unit-tested offline.
"""
import numpy as np
from PIL import Image, ImageFilter

MODEL_W, MODEL_H = 768, 1024      # the size IDM-VTON works at (3:4)

Box = tuple[int, int, int, int]   # (left, top, width, height) of the real photo inside the padded image


# ----------------------------------------------------------------------------
# 1) Pad to 3:4 (never stretch) and map the result back
# ----------------------------------------------------------------------------
def _edge_band(edge: np.ndarray, length: int, bg: np.ndarray, fade: float = 0.85) -> np.ndarray:
    """Build padding next to one photo edge.
    edge:  (n, 3) colours of that edge (smoothed here so a person touching the edge doesn't leave sharp streaks)
    Returns (length, n, 3); row 0 touches the photo and fades towards the photo's overall background colour."""
    sigma = max(2.0, len(edge) * 0.02)
    line = Image.fromarray(np.clip(edge, 0, 255).astype(np.uint8)[None, :, :])
    edge = np.asarray(line.filter(ImageFilter.GaussianBlur(sigma)), dtype=np.float32)[0]
    t = (np.arange(length, dtype=np.float32) + 1) / length          # 0..1, distance from the photo
    a = (fade * t)[:, None, None]
    return edge[None] * (1 - a) + bg[None, None] * a


def pad_to_3_4(img: Image.Image) -> tuple[Image.Image, Box]:
    """Add padding (top/bottom if the photo is wider than 3:4, left/right if taller) so the
    image becomes exactly 3:4. The padding continues the photo's edge colours.
    Returns (padded image, box of the original photo inside it)."""
    img = img.convert("RGB")
    w, h = img.size
    if w * 4 > h * 3:                       # wider than 3:4 -> pad top/bottom
        new_w, new_h = w, -(-w * 4 // 3)
    else:                                   # taller than (or equal to) 3:4 -> pad left/right
        new_w, new_h = -(-h * 3 // 4), h
    if (new_w, new_h) == (w, h):
        return img.copy(), (0, 0, w, h)

    a = np.asarray(img, dtype=np.float32)
    bg = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0)   # overall background colour
    left, top = (new_w - w) // 2, (new_h - h) // 2
    canvas = np.empty((new_h, new_w, 3), dtype=np.float32)
    canvas[top:top + h, left:left + w] = a
    if new_h > h:
        k = max(1, h // 100)
        canvas[:top] = _edge_band(a[:k].mean(0), top, bg)[::-1]
        canvas[top + h:] = _edge_band(a[-k:].mean(0), new_h - top - h, bg)
    else:
        k = max(1, w // 100)
        canvas[:, :left] = _edge_band(a[:, :k].mean(1), left, bg).transpose(1, 0, 2)[:, ::-1]
        canvas[:, left + w:] = _edge_band(a[:, -k:].mean(1), new_w - left - w, bg).transpose(1, 0, 2)
    return Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)), (left, top, w, h)


def to_model_size(padded: Image.Image) -> Image.Image:
    """Uniform resize of the (already 3:4) padded image to 768x1024 - no distortion."""
    return padded.resize((MODEL_W, MODEL_H), Image.LANCZOS)


def padded_size(box: Box) -> tuple[int, int]:
    """Size of the padded image, recomputed from the box (3:4 of the padded dimension)."""
    left, top, w, h = box
    if w * 4 > h * 3:
        return w, -(-w * 4 // 3)
    return -(-h * 3 // 4), h


def unpad(result: Image.Image, box: Box) -> Image.Image:
    """Model output (768x1024) -> padded size -> crop out the original photo area.
    The result has exactly the original photo's size and shape."""
    left, top, w, h = box
    pw, ph = padded_size(box)
    return result.convert("RGB").resize((pw, ph), Image.LANCZOS).crop((left, top, left + w, top + h))


def mask_to_original(mask768: np.ndarray, box: Box) -> Image.Image:
    """A 768x1024 mask -> soft 'L' image in the original photo's coordinates."""
    left, top, w, h = box
    pw, ph = padded_size(box)
    m = Image.fromarray((mask768 * 255).astype(np.uint8)).resize((pw, ph), Image.BILINEAR)
    return m.crop((left, top, left + w, top + h))


def box_mask_768(box: Box) -> np.ndarray:
    """True where the 768x1024 model image holds real photo (False = padding)."""
    left, top, w, h = box
    pw, ph = padded_size(box)
    sx, sy = MODEL_W / pw, MODEL_H / ph
    m = np.zeros((MODEL_H, MODEL_W), dtype=bool)
    m[int(round(top * sy)):int(round((top + h) * sy)), int(round(left * sx)):int(round((left + w) * sx))] = True
    return m


# ----------------------------------------------------------------------------
# 2) Mask: read the Space's auto mask, then make it a bit bigger
# ----------------------------------------------------------------------------
def extract_mask(masked_img: Image.Image, sent_img: Image.Image) -> np.ndarray:
    """The Space's 'masked image' shows the garment area as flat mid-grey (128).
    Recover that area as a boolean mask (same size as the image we sent)."""
    sent = sent_img.convert("RGB")
    m = np.asarray(masked_img.convert("RGB").resize(sent.size), dtype=np.int16)
    o = np.asarray(sent, dtype=np.int16)
    grey = (np.abs(m - 128) <= 4).all(axis=2)
    unchanged = (np.abs(m - o) <= 3).all(axis=2)          # genuinely grey pixels of the photo are not mask
    raw = Image.fromarray(((grey & ~unchanged) * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))
    return np.asarray(raw) > 127


def _smooth(mask: np.ndarray, radius: float) -> np.ndarray:
    im = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(im) > 110


def expand_mask(mask: np.ndarray, photo: Image.Image, valid: np.ndarray,
                side_px: int, up_px: int) -> np.ndarray:
    """Grow the garment mask so the blazer is not drawn inside the body outline.
      - grows `side_px` sideways (shoulders, torso sides, arms) and `up_px` upwards, NEVER downwards
        (keeps the jeans / lower body untouched)
      - the NEW area never covers skin-coloured pixels (face, neck, hands stay outside the mask)
      - never grows into the padding (`valid` = real-photo area)."""
    grown = mask.copy()
    for dx in range(1, side_px + 1):
        grown[:, dx:] |= mask[:, :-dx]
        grown[:, :-dx] |= mask[:, dx:]
    up = grown.copy()
    for dy in range(1, up_px + 1):
        up[:-dy] |= grown[dy:]
    ycc = np.asarray(photo.convert("YCbCr"), dtype=np.int16)
    y, cb, cr = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    skin = (cb >= 77) & (cb <= 127) & (cr >= 133) & (cr <= 173) & (y > 50)
    out = mask | (up & ~skin)
    return _smooth(out, 3) & valid | (mask & valid)


# ----------------------------------------------------------------------------
# 3) Put the original pixels back outside the mask
# ----------------------------------------------------------------------------
def composite(original: Image.Image, generated: Image.Image, mask_img: Image.Image) -> Image.Image:
    """Inside the mask: the generated garment. Outside: the ORIGINAL pixels (face, hair, neck, hands,
    jeans, background are therefore identical to the upload). The edge is feathered for a soft blend."""
    feather = max(2.0, original.width * 0.004)
    alpha = mask_img.convert("L").filter(ImageFilter.GaussianBlur(feather))
    return Image.composite(generated.convert("RGB"), original.convert("RGB"), alpha)
