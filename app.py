# Vercel entrypoint: it looks for a FastAPI `app` in a root-level app.py / index.py / main.py.
from backend.main import app  # noqa: F401
