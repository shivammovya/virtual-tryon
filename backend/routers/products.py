"""Product API. GET is public; POST/PUT/DELETE need the admin cookie."""
import csv
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from .. import db, storage
from ..auth import require_admin
from ..images import BadInput, MAX_BYTES, read_image, remove_background

router = APIRouter(prefix="/api/products")


def clean_fields(name: str, price: float, category: str, gender: str):
    """Validate and normalise the text fields of a product."""
    name, category, gender = name.strip(), category.strip().lower(), gender.strip().lower()
    if not name or len(name) > 100:
        raise BadInput("Product name is required (max 100 characters).")
    if price < 0:
        raise BadInput("Price cannot be negative.")
    if not category:
        raise BadInput("Category is required.")
    if gender not in db.GENDERS:
        raise BadInput("Gender must be men, women or unisex.")
    return name, round(price, 2), category, gender


def store_image(data: bytes, remove_bg: bool) -> tuple[str, bool]:
    """Validate, optionally remove background, save into data/products. Returns (filename, bg_removed)."""
    img = read_image(data, "clothing")
    removed = False
    if remove_bg:
        img, removed = remove_background(img)
    return storage.save_product_image(img), removed


def delete_image_file(filename: str) -> None:
    storage.delete_product_image(filename)


@router.get("")
def list_products(response: Response, category: str | None = None, gender: str | None = None):
    response.headers["Cache-Control"] = "no-store"   # so the customer app always sees fresh data
    return {"products": db.list_products(category, gender)}


@router.post("", dependencies=[Depends(require_admin)])
def add_product(
    name: str = Form(...), price: float = Form(...), category: str = Form(...), gender: str = Form(...),
    remove_bg: bool = Form(True), image: UploadFile = File(...),
):
    fields = clean_fields(name, price, category, gender)
    filename, removed = store_image(image.file.read(MAX_BYTES + 1), remove_bg)
    product = db.add_product(*fields, filename)
    return {"success": True, "product": product, "background_removed": removed,
            "warning": None if (removed or not remove_bg) else
            "Background removal isn't installed - please use clean front-view photos on a plain background."}


@router.put("/{pid}", dependencies=[Depends(require_admin)])
def edit_product(
    pid: int,
    name: str = Form(...), price: float = Form(...), category: str = Form(...), gender: str = Form(...),
    remove_bg: bool = Form(True), image: UploadFile | None = File(None),
):
    old = db.get_product(pid)
    if not old:
        raise HTTPException(404, "Product not found.")
    fields = clean_fields(name, price, category, gender)
    filename = old["image"]
    if image is not None and image.filename:           # a new image replaces the old one
        filename, _ = store_image(image.file.read(MAX_BYTES + 1), remove_bg)
    product = db.update_product(pid, *fields, filename)
    if filename != old["image"]:
        delete_image_file(old["image"])
    return {"success": True, "product": product}


@router.delete("/{pid}", dependencies=[Depends(require_admin)])
def remove_product(pid: int):
    old = db.get_product(pid)
    if not old:
        raise HTTPException(404, "Product not found.")
    db.delete_product(pid)
    delete_image_file(old["image"])
    return {"success": True}


@router.post("/bulk/upload", dependencies=[Depends(require_admin)])
def bulk_upload(csv_file: UploadFile = File(...), images: list[UploadFile] = File(...),
                remove_bg: bool = Form(True)):
    """CSV columns: name,price,category,gender,image   (image = file name among the uploaded images)."""
    by_name = {f.filename: f for f in images}
    try:
        rows = list(csv.DictReader(io.StringIO(csv_file.file.read(MAX_BYTES).decode("utf-8-sig"))))
    except UnicodeDecodeError:
        raise BadInput("The CSV must be UTF-8 text.")
    added, errors = 0, []
    for i, row in enumerate(rows, start=2):               # row 1 is the header
        try:
            fields = clean_fields(row.get("name", ""), float(row.get("price", "")),
                                  row.get("category", ""), row.get("gender", ""))
            up = by_name.get((row.get("image") or "").strip())
            if not up:
                raise BadInput(f"image '{row.get('image')}' was not uploaded.")
            filename, _ = store_image(up.file.read(MAX_BYTES + 1), remove_bg)
            db.add_product(*fields, filename)
            added += 1
        except (BadInput, ValueError) as e:
            errors.append(f"CSV row {i}: {e}")
        except Exception as e:                          # one bad row must not break the whole upload
            errors.append(f"CSV row {i}: unexpected error ({type(e).__name__})")
    return {"success": True, "added": added, "errors": errors}
