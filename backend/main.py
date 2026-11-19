"""FastAPI app: customer page (/), admin panel (/admin) and the JSON APIs."""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .images import BadInput
from .routers import admin, products, tryon

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

db.init_db()
app = FastAPI(title="Virtual Try-On")
# CORS: open for local development. Restrict allow_origins before going public.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.mount("/outputs", StaticFiles(directory=config.OUTPUTS_DIR), name="outputs")
if not config.USE_SUPABASE:   # with Supabase, images are served from its public bucket
    app.mount("/product-images", StaticFiles(directory=config.PRODUCTS_DIR), name="product-images")
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR / "static"), name="static")

app.include_router(tryon.router)
app.include_router(products.router)
app.include_router(admin.router)


@app.exception_handler(BadInput)
async def bad_input_handler(request: Request, exc: BadInput):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.get("/api/storage-mode")
def storage_mode(test: bool = False):
    """Shows which storage the running app uses (never the keys). Add ?test=1 to ping Supabase."""
    info = {"storage": "supabase" if config.USE_SUPABASE else "local",
            "supabase_url_set": bool(config.SUPABASE_URL), "supabase_key_set": bool(config.SUPABASE_KEY)}
    if test and config.USE_SUPABASE:
        import httpx
        h = {"apikey": config.SUPABASE_KEY, "Authorization": f"Bearer {config.SUPABASE_KEY}"}
        for name, url in (("database", f"{config.SUPABASE_URL}/rest/v1/products?select=id&limit=1"),
                          ("storage_bucket", f"{config.SUPABASE_URL}/storage/v1/bucket/product-images")):
            try:
                r = httpx.get(url, headers=h, timeout=15)
                info[name] = "ok" if r.status_code == 200 else f"failed ({r.status_code}): {r.text[:150]}"
            except Exception as e:
                info[name] = f"failed: {type(e).__name__}"
    return info


@app.get("/")
def customer_app():
    return FileResponse(config.FRONTEND_DIR / "index.html")
