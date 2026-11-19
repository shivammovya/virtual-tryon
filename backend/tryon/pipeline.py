"""Try-on pipeline: keeps the person's proportions exactly like the upload.

  1. pad the person photo (and the garment) to 3:4 - never stretch - and send 768x1024 to the model
  2. pass 1: the model makes its own garment mask (and a first result)
  3. pass 2 (optional): redo it with that mask enlarged ~20 px (shoulders / sides / arms, not downwards,
     not over skin) so the blazer isn't drawn inside the body outline. If pass 2 fails, pass 1 is used.
  4. result -> back to padded size -> crop out the photo area = exactly the original size and shape
  5. paste the ORIGINAL pixels back outside the mask (face, hair, neck, hands, jeans, background)
"""
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import fit
from .base import TryOnError, TryOnProvider

log = logging.getLogger("tryon.pipeline")


@dataclass
class PipelineResult:
    image: Image.Image                    # same size / shape as the uploaded person photo
    mask: Image.Image | None = None       # mask used for compositing, original coordinates
    debug: dict = field(default_factory=dict)


def _save_png(img: Image.Image, folder: Path, tag: str) -> Path:
    path = folder / f"{uuid.uuid4().hex}_{tag}.png"
    img.save(path, "PNG")
    return path


def run(provider: TryOnProvider, person_path: str, garment_path: str, garment_desc: str,
        denoise_steps: int, seed: int, work_dir: Path,
        expand_mask: bool = True, expand_pct: float = 2.6) -> PipelineResult:
    temp: list[Path] = []
    info: dict = {}
    try:
        person = Image.open(person_path).convert("RGB")
        garment = Image.open(garment_path).convert("RGB")

        # 1) pad (never stretch) -> 768x1024 for both images
        person_pad, box = fit.pad_to_3_4(person)
        garment_pad, _ = fit.pad_to_3_4(garment)
        person_in = fit.to_model_size(person_pad)
        garment_in = fit.to_model_size(garment_pad)
        p_path, g_path = _save_png(person_in, work_dir, "person"), _save_png(garment_in, work_dir, "garment")
        temp += [p_path, g_path]
        info.update(original_size=list(person.size), padding_box=list(box), model_input=[fit.MODEL_W, fit.MODEL_H])

        # 2) pass 1: Space's own mask. If we plan a 2nd pass, use the minimum steps here to save quota.
        want_pass2 = expand_mask and provider.supports_mask
        steps1 = min(denoise_steps, 20) if want_pass2 else denoise_steps
        out1, masked1 = provider.try_on_with_mask(str(p_path), str(g_path), garment_desc,
                                                  denoise_steps=steps1, seed=seed)
        out_path, mask768 = out1, None
        if masked1:
            m = fit.extract_mask(Image.open(masked1), person_in)
            coverage = m.mean()
            if 0.005 < coverage < 0.6:
                mask768 = m
            else:
                log.warning("Mask extraction looked wrong (coverage %.3f) - not using it", coverage)
        info["mask_found"] = mask768 is not None

        # 3) pass 2 with the enlarged mask
        info["two_pass"] = False
        if want_pass2 and mask768 is not None:
            side = max(1, round(fit.MODEL_W * expand_pct / 100))
            up = max(1, side // 3)
            valid = fit.box_mask_768(box)                 # real photo area (padding excluded)
            mask768 = mask768 & valid                     # the model may have drawn into the padding - ignore that
            big = fit.expand_mask(mask768, person_in, valid, side, up)
            mask_png = Image.new("RGBA", big.shape[::-1], (0, 0, 0, 0))
            mask_png.paste((255, 255, 255, 255), mask=Image.fromarray((big * 255).astype(np.uint8)))
            mp = _save_png(mask_png, work_dir, "mask")
            temp.append(mp)
            try:
                out_path, _ = provider.try_on_with_mask(str(p_path), str(g_path), garment_desc,
                                                        denoise_steps=denoise_steps, seed=seed, mask_path=str(mp))
                info.update(two_pass=True, mask_expand_px=side, mask_grow_up_px=up,
                            mask_area_before_pct=round(float(mask768.mean()) * 100, 2),
                            mask_area_after_pct=round(float(big.mean()) * 100, 2))
                mask768 = big
            except TryOnError as e:      # e.g. quota used up: keep the pass-1 result
                log.warning("Pass 2 failed (%s) - using the pass-1 result", e.message)
                out_path = out1
                info["pass2_error"] = e.message

        # 4) back to the original photo's size and shape
        generated = fit.unpad(Image.open(out_path), box)

        # 5) original pixels outside the mask
        mask_img = None
        if mask768 is not None:
            mask_img = fit.mask_to_original(mask768, box)
            final = fit.composite(person, generated, mask_img)
        else:
            final = generated
        assert final.size == person.size
        return PipelineResult(final, mask_img, info)
    finally:
        for p in temp:
            p.unlink(missing_ok=True)


# ----------------------------------------------------------------------------
# Debug: side-by-side image + measurements
# ----------------------------------------------------------------------------
def _span(row: np.ndarray) -> int:
    xs = np.flatnonzero(row)
    return int(xs[-1] - xs[0] + 1) if len(xs) else 0


def _pct(new: float, old: float) -> float | None:
    return round((new - old) / old * 100, 2) if old else None


def side_by_side(original: Image.Image, result: Image.Image, gap: int = 8) -> Image.Image:
    """Original and result next to each other, same height."""
    h = original.height
    result = result.resize((round(result.width * h / result.height), h), Image.LANCZOS)
    canvas = Image.new("RGB", (original.width + gap + result.width, h), "white")
    canvas.paste(original, (0, 0))
    canvas.paste(result, (original.width + gap, 0))
    return canvas


def measure(original: Image.Image, res: PipelineResult, silhouette_fn=None) -> dict:
    """Checks that the result keeps the person's size and proportions."""
    final = res.image
    d = dict(res.debug)
    d["size_equal"] = final.size == original.size
    d["aspect_error_pct"] = _pct(final.width / final.height, original.width / original.height)
    if res.mask is not None:
        m = np.asarray(res.mask) > 127
        d["mask_coverage_pct"] = round(float(m.mean()) * 100, 2)
        outside = ~m
        diff = np.abs(np.asarray(final, np.int16) - np.asarray(original, np.int16)).mean(axis=2)
        # (the feathered edge blends a few px, so allow a tiny residual)
        d["mean_pixel_change_outside_mask"] = round(float(diff[outside].mean()), 3) if outside.any() else 0.0
    if silhouette_fn:
        try:
            so, sr = silhouette_fn(original), silhouette_fn(final)
            if so is not None and sr is not None and res.mask is not None:
                rows = np.flatnonzero(np.asarray(res.mask).max(axis=1) > 127)
                top_m, h_m = int(rows[0]), int(rows[-1] - rows[0] + 1)
                sil_rows = np.flatnonzero(so.any(axis=1))
                top_s = int(sil_rows[0]) if len(sil_rows) else 0
                shoulder_row = min(top_m + int(0.06 * h_m), original.height - 1)
                sh = _pct(_span(sr[shoulder_row]), _span(so[shoulder_row]))
                d["shoulder_width_diff_pct"] = sh
                if top_m - top_s > 8:   # head visible above the garment
                    head_row = top_s + (top_m - top_s) // 2
                    d["head_width_diff_pct"] = _pct(_span(sr[head_row]), _span(so[head_row]))
                d["within_3pct"] = all(abs(v) <= 3 for k, v in d.items()
                                       if k in ("shoulder_width_diff_pct", "head_width_diff_pct") and v is not None)
            else:
                d["silhouette"] = "skipped (rembg not installed or no mask)"
        except Exception as e:                    # debug must never break a try-on
            log.exception("Silhouette measurement failed")
            d["silhouette"] = f"failed: {type(e).__name__}"
    return d
