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
app.mount("/product-images", StaticFiles(directory=config.PRODUCTS_DIR), name="product-images")
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR / "static"), name="static")

app.include_router(tryon.router)
app.include_router(products.router)
app.include_router(admin.router)


@app.exception_handler(BadInput)
async def bad_input_handler(request: Request, exc: BadInput):
    return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.get("/")
def customer_app():
    return FileResponse(config.FRONTEND_DIR / "index.html")
