"""Offline checks for backend/tryon/fit.py (no network, no model).
Run:  python tests/test_fit.py        (or: pytest tests)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.tryon import fit  # noqa: E402

SHAPES = {"square": (900, 900), "tall phone": (720, 1560), "wide": (1000, 640)}


def fake_photo(w, h):
    """Light backdrop, a dark circular 'head' (should stay a circle) and a blue 'torso'."""
    img = Image.new("RGB", (w, h), (225, 228, 232))
    d = ImageDraw.Draw(img)
    r = int(min(w, h) * 0.12)
    cx, cy = w // 2, int(h * 0.25)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(30, 30, 30))
    d.rectangle((int(w * 0.3), int(h * 0.38), int(w * 0.7), h - 1), fill=(60, 90, 160))   # touches the bottom edge
    return img


def dark_bbox_ratio(img):
    a = np.asarray(img.convert("L")) < 60
    ys, xs = np.where(a[: int(img.height * 0.36)])             # only the head
    return (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)


def test_roundtrip_keeps_size_and_shape():
    for name, (w, h) in SHAPES.items():
        photo = fake_photo(w, h)
        padded, box = fit.pad_to_3_4(photo)
        assert abs(padded.width / padded.height - 0.75) < 0.002, name          # exactly 3:4
        assert box[2:] == (w, h)
        model_in = fit.to_model_size(padded)
        assert model_in.size == (768, 1024)
        # pretend the model returned its input unchanged
        out = fit.unpad(model_in, box)
        assert out.size == (w, h), (name, out.size)                            # same size & shape as the upload
        mae = np.abs(np.asarray(out, np.int16) - np.asarray(photo, np.int16)).mean()
        assert mae < 4, (name, mae)
        # the round head must still be round (a stretch would change this ratio)
        assert abs(dark_bbox_ratio(out) - dark_bbox_ratio(photo)) < 0.03, name
        print(f"  ok {name:11s} {w}x{h} -> padded {padded.size} -> back {out.size}, MAE {mae:.2f}")


def test_padding_is_on_the_right_sides():
    _, (l, t, w, h) = fit.pad_to_3_4(fake_photo(900, 900))
    assert l == 0 and t > 0                    # wider than 3:4 -> top/bottom
    _, (l, t, w, h) = fit.pad_to_3_4(fake_photo(720, 1560))
    assert t == 0 and l > 0                    # taller than 3:4 -> left/right
    _, (l, t, w, h) = fit.pad_to_3_4(fake_photo(768, 1024))
    assert (l, t) == (0, 0)                    # already 3:4 -> untouched


def test_padding_does_not_streak_from_a_person_touching_the_edge():
    photo = fake_photo(1000, 640)              # blue torso touches the bottom edge
    padded, (l, t, w, h) = fit.pad_to_3_4(photo)
    far_bottom = np.asarray(padded)[-3:].reshape(-1, 3).mean(0)
    # far from the photo the padding should have faded towards the backdrop, not stay saturated blue
    assert far_bottom[2] - far_bottom[0] < 60, far_bottom


def test_extract_and_expand_mask():
    sent = Image.new("RGB", (768, 1024), (200, 200, 200))
    d = ImageDraw.Draw(sent)
    d.rectangle((300, 520, 330, 560), fill=(224, 172, 150))     # a 'hand' (skin) just beside the torso, below the mask
    d.rectangle((335, 300, 360, 340), fill=(224, 172, 150))     # skin right next to the mask's right edge
    masked = sent.copy()
    ImageDraw.Draw(masked).rectangle((200, 250, 334, 520), fill=(128, 128, 128))
    m = fit.extract_mask(masked, sent)
    truth = np.zeros((1024, 768), bool); truth[250:521, 200:335] = True
    iou = (m & truth).sum() / (m | truth).sum()
    assert iou > 0.97, iou

    valid = np.ones((1024, 768), bool)
    big = fit.expand_mask(m, sent, valid, side_px=20, up_px=6)
    ys, xs = np.where(big)
    assert xs.min() <= 200 - 17 and xs.min() >= 200 - 21, xs.min()      # grew ~20px to the left
    assert ys.max() <= 520 + 1, ys.max()                                # never grew downwards
    assert ys.min() >= 250 - 7 and ys.min() < 250 - 3, ys.min()         # grew only a little upwards
    assert not big[300:340, 336:361].any() or big[300:340, 336:361].mean() < 0.1   # skin beside the mask stays out
    # padding is never entered
    valid2 = valid.copy(); valid2[:, :190] = False
    assert not fit.expand_mask(m, sent, valid2, 20, 6)[:, :190].any()
    print(f"  ok mask: IoU {iou:.3f}, grew left {200 - xs.min()}px, up {250 - ys.min()}px, down {ys.max() - 520}px")


def test_composite_restores_original_outside_mask():
    orig = fake_photo(600, 800)
    gen = Image.new("RGB", orig.size, (255, 0, 0))
    mask = Image.new("L", orig.size, 0); ImageDraw.Draw(mask).rectangle((200, 300, 400, 600), fill=255)
    out = np.asarray(fit.composite(orig, gen, mask), np.int16)
    o = np.asarray(orig, np.int16)
    assert np.abs(out[:200] - o[:200]).max() == 0                       # far outside: identical
    assert (out[450, 300] == (255, 0, 0)).all()                         # inside: generated


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            print(name); fn()
    print("ALL OK")
