# Virtual Try-On Store

Two apps in one FastAPI server:

| URL | What |
|---|---|
| `/` | **Customer app** — *Store Collection*: pick a product from the carousel, then upload a photo (or take one with the camera) and click *Try It On*. The upload section includes a Do / Don't pose guide (arms relaxed, not folded) |
| `/admin` | **Store owner panel** — login, add/edit/delete products, bulk CSV upload. Redirects to `/admin/login` if not logged in |

Try-on model: free Hugging Face Space `yisol/IDM-VTON` (via `gradio_client`).
Database: SQLite (`data/store.db`). Product images: `data/products/`. Both are created automatically.
No Firebase/Supabase needed — everything runs locally with zero accounts.

## Folder structure
```
virtual-tryon/
├── backend/
│   ├── main.py              # app setup, mounts, routers
│   ├── config.py            # .env settings + provider factory
│   ├── db.py                # SQLite product storage (swap this file for Supabase/Firebase later)
│   ├── auth.py              # admin login (signed cookie)
│   ├── images.py            # image validation / resize / background removal
│   ├── routers/
│   │   ├── tryon.py         # POST /api/tryon
│   │   ├── products.py      # GET/POST/PUT/DELETE /api/products (+ bulk)
│   │   └── admin.py         # /admin pages + login/logout
│   └── tryon/               # base.py (interface), huggingface.py (IDM-VTON), pipeline.py + fit.py (padding / mask / blending)
├── frontend/
│   ├── index.html           # customer app
│   ├── admin/login.html
│   ├── admin/dashboard.html
│   └── static/style.css, common.js
├── tests/test_fit.py        # offline geometry tests
├── data/                    # database + product images (gitignored)
├── uploads/  outputs/       # temp files (gitignored)
├── .env.example  requirements.txt  requirements-optional.txt
```

## Setup (always inside the virtual environment)

### Windows (PowerShell)
```powershell
cd virtual-tryon
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: automatic background removal
copy .env.example .env                     # then edit .env (see below)
python -m uvicorn backend.main:app --reload --port 8765
deactivate                                 # when done
```
### Mac / Linux
```bash
cd virtual-tryon
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-optional.txt
cp .env.example .env
python -m uvicorn backend.main:app --reload --port 8765
deactivate
```
Open **http://localhost:8765** (customer) and **http://localhost:8765/admin** (owner).
If you change `.env`, restart the server.

## Configure `.env`
```
TRYON_PROVIDER=huggingface
HF_TOKEN=                  # optional but recommended: free token from huggingface.co/settings/tokens
ADMIN_EMAIL=you@yourstore.com
ADMIN_PASSWORD=a-long-password   # there is NO default; admin login is disabled until you set this
SECRET_KEY=<random>        # python -c "import secrets;print(secrets.token_hex(32))"
```
Secrets live only on the server in `.env` — the frontend never sees them.

## Camera capture
The upload box has a **Take a photo with camera** button (front camera, via `getUserMedia`). The captured JPEG goes into the same file input as a normal upload, so all validation and the try-on flow are identical.
Browsers only allow camera access on **HTTPS or `http://localhost`** — over a plain `http://<LAN-IP>` address (e.g. a phone on your Wi-Fi) the button shows a "camera isn't available" message; use HTTPS (deploy, or a tunnel such as ngrok / Cloudflare Tunnel).

## Admin panel
- **Add Product:** image, name, price, category, gender. Background is removed automatically if `rembg` is installed
  (first use downloads a ~170 MB model). Without it you get a warning to use clean front-view photos on a plain background.
- **Edit / Delete** from the product table. The customer's *Store Collection* tab reloads products every time it's opened, so changes show up immediately.
- **Bulk upload:** a CSV with columns `name,price,category,gender,image` plus the image files; `image` must match a selected file name.

## API
| Route | Auth | Notes |
|---|---|---|
| `POST /api/tryon` | public | `person_image` + either `garment_image` **or** `product_id`; optional `garment_desc`, `auto_crop`, `denoise_steps` (20–40), `seed` → `{success, image_url}` |
| `GET /api/products?category=&gender=` | public | |
| `POST /api/products` | admin | multipart: `image, name, price, category, gender, remove_bg` |
| `PUT /api/products/{id}` | admin | same fields, `image` optional |
| `DELETE /api/products/{id}` | admin | |
| `POST /api/products/bulk/upload` | admin | `csv_file`, `images[]` |
| `POST /api/admin/login`, `/api/admin/logout` | | |

## How the try-on keeps the person's proportions
The model needs 768×1024 (3:4) and **stretches** any other shape (that made people look thinner/taller), so `backend/tryon/pipeline.py`:
1. **Pads** the person photo (and the garment) to 3:4 with the photo's own edge colours, then resizes uniformly to 768×1024.
2. Pass 1: the Space makes its mask. Pass 2: the mask is enlarged ~20 px (shoulders, torso sides, arms; never downwards, never over skin) and the try-on is redone, so the garment isn't drawn inside the body outline. If pass 2 fails, the pass-1 result is used.
3. Resizes the result back and **crops out the photo area** → same size and shape as the upload (after the 1024 px upload limit).
4. Puts the **original pixels back outside the mask** (soft edge): face, hair, neck, hands, jeans and background are unchanged.

Costs: pass 2 doubles GPU use per try-on. Set `TRYON_EXPAND_MASK=false` in `.env` to use one pass (padding fix still applies).
`TRYON_MASK_EXPAND_PCT` (default 2.6 = ~20 px) controls the growth.

**Debug:** add `debug=true` to `POST /api/tryon` (the UI doesn't) to get `debug.side_by_side_url` (original | result, same height) and measurements:
size/aspect match, pixel change outside the mask, and shoulder/head width difference in % (needs `rembg`).
Offline geometry tests: `python tests/test_fit.py`.

## Known limits
- The free Space has a queue (30–120 s, sometimes more) and a **daily GPU quota**; anonymous users run out quickly — add `HF_TOKEN`. Free accounts still have a small daily quota; if you see "Daily free quota reached" with a token already set, your own quota is used up (set `TRYON_EXPAND_MASK=false` to halve usage) or the server needs a restart after editing `.env`.
- The Space can be sleeping, down or changed at any time. Swap Space: edit `SPACE_NAME`/`_call_space()` in `backend/tryon/huggingface.py`.
- Needs a real person in the photo. Best quality: front-facing, well-lit; clothing on a plain background; upper-body items work best.
- Images: JPG/PNG, max 10 MB. Results deleted after 1 hour, temp uploads right after use.
- Going public: serve over HTTPS (set `secure=True` on the cookie in `routers/admin.py`), restrict CORS in `main.py`, and add login rate-limiting.

## Adding a new try-on provider
1. New file `backend/tryon/<name>.py` with a `TryOnProvider` subclass implementing `try_on(...)`.
2. Add a branch in `get_provider()` in `backend/config.py`.
3. Set `TRYON_PROVIDER=<name>` in `.env`.
