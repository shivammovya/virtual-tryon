"""POST /api/tryon - generate a try-on image."""
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from .. import config, db, images
from ..images import BadInput, save_upload
from ..tryon import pipeline
from ..tryon.base import TryOnError

log = logging.getLogger("tryon")
router = APIRouter()
provider = config.get_provider()      # created once, reused for every request
OUTPUT_MAX_AGE = 60 * 60              # delete outputs older than 1 hour


def cleanup_old_outputs() -> None:
    cutoff = time.time() - OUTPUT_MAX_AGE
    for f in config.OUTPUTS_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


@router.post("/api/tryon")
def tryon(
    person_image: UploadFile = File(...),
    garment_image: UploadFile | None = File(None),   # Tab 1: custom clothing upload
    product_id: int | None = Form(None),             # Tab 2: store product
    garment_desc: str = Form("a garment"),
    auto_crop: bool = Form(False),
    denoise_steps: int = Form(30),
    seed: int = Form(42),
    debug: bool = Form(False),                       # extra: side-by-side image + measurements
):
    # Plain `def` so FastAPI runs this slow call in a worker thread.
    cleanup_old_outputs()
    temp_files: list[Path] = []
    try:
        if not 20 <= denoise_steps <= 40:
            raise BadInput("denoise_steps must be between 20 and 40.")

        person_path = save_upload(person_image, "person", config.UPLOADS_DIR)
        temp_files.append(person_path)

        if product_id is not None:
            product = db.get_product(product_id)
            if not product:
                raise BadInput("That product no longer exists. Please pick another one.")
            garment_path = config.PRODUCTS_DIR / product["image"]   # stored image, not a temp file
            garment_desc = f"{product['name']} ({product['category']})"
        elif garment_image is not None and garment_image.filename:
            garment_path = save_upload(garment_image, "clothing", config.UPLOADS_DIR)
            temp_files.append(garment_path)
        else:
            raise BadInput("Please upload a clothing image or select a product.")

        # auto_crop is ignored: the pipeline pads to 3:4 itself, which never distorts the person.
        result = pipeline.run(
            provider, str(person_path), str(garment_path), garment_desc.strip() or "a garment",
            denoise_steps=denoise_steps, seed=seed, work_dir=config.UPLOADS_DIR,
            expand_mask=config.EXPAND_MASK, expand_pct=config.MASK_EXPAND_PCT,
        )
        out_name = f"{uuid.uuid4().hex}.png"
        result.image.save(config.OUTPUTS_DIR / out_name, "PNG")
        response = {"success": True, "image_url": f"/outputs/{out_name}"}

        if debug:   # original + result side by side (same height) and proportion measurements
            original = Image.open(person_path).convert("RGB")
            cmp_name = f"{uuid.uuid4().hex}_compare.png"
            pipeline.side_by_side(original, result.image).save(config.OUTPUTS_DIR / cmp_name, "PNG")
            response["debug"] = pipeline.measure(original, result, images.person_silhouette)
            response["debug"]["side_by_side_url"] = f"/outputs/{cmp_name}"
        return response

    except BadInput as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except TryOnError as e:
        log.error("Try-on failed: %s", e.message)
        return JSONResponse({"success": False, "error": e.message}, status_code=e.status_code)
    except Exception:
        log.exception("Unexpected error")
        return JSONResponse({"success": False, "error": "Something went wrong on the server."}, status_code=500)
    finally:
        for p in temp_files:       # always delete temp inputs
            p.unlink(missing_ok=True)
