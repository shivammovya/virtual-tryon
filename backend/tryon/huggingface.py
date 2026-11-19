"""Try-on provider that calls a free Hugging Face Space through gradio_client."""
import logging
import threading

from gradio_client import Client, handle_file

from .base import TryOnError, TryOnProvider

log = logging.getLogger("tryon.huggingface")

# --- To swap to another Space (e.g. CatVTON / Kolors), change these and the
# --- parameters inside _call_space() below. Run Client("<space>").view_api()
# --- to see what the new Space expects.
SPACE_NAME = "yisol/IDM-VTON"
API_NAME = "/tryon"
TIMEOUT_SECONDS = 180


class HuggingFaceTryOn(TryOnProvider):
    def __init__(self, hf_token: str | None = None):
        self.hf_token = hf_token or None
        self._client: Client | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> Client:
        """Create the Client once, then reuse it."""
        with self._lock:
            if self._client is None:
                log.info("Connecting to Space %s ...", SPACE_NAME)
                # NOTE: gradio_client >= 2.x uses `token=`; older used `hf_token=`.
                try:
                    self._client = Client(SPACE_NAME, token=self.hf_token)
                except TypeError:
                    self._client = Client(SPACE_NAME, hf_token=self.hf_token)
            return self._client

    supports_mask = True

    def _call_space(self, person_path, garment_path, garment_desc,
                    auto_crop, denoise_steps, seed, mask_path=None):
        """The one place that knows the Space's parameter names.
        mask_path=None  -> the Space makes its own mask.
        mask_path=<png> -> use our mask (white = area to replace) drawn as an editor layer."""
        client = self._get_client()
        layers = [handle_file(mask_path)] if mask_path else []
        job = client.submit(
            dict={"background": handle_file(person_path), "layers": layers, "composite": None},
            garm_img=handle_file(garment_path),
            garment_des=garment_desc,
            is_checked=mask_path is None,  # True = auto-generate mask
            is_checked_crop=auto_crop,     # auto-crop & resize (we pad ourselves, so this stays False)
            denoise_steps=denoise_steps,
            seed=seed,
            api_name=API_NAME,
        )
        try:
            result = job.result(timeout=TIMEOUT_SECONDS)
        except Exception:
            job.cancel()
            raise
        return result[0], result[1]  # (output image, masked preview - the garment area shown as grey)

    def try_on(self, person_path, garment_path, garment_desc,
               auto_crop=False, denoise_steps=30, seed=42) -> str:
        return self.try_on_with_mask(person_path, garment_path, garment_desc,
                                     denoise_steps=denoise_steps, seed=seed, auto_crop=auto_crop)[0]

    def try_on_with_mask(self, person_path, garment_path, garment_desc,
                         denoise_steps=30, seed=42, mask_path=None, auto_crop=False):
        last_error: Exception | None = None
        for attempt in (1, 2):  # retry once
            try:
                return self._call_space(person_path, garment_path, garment_desc,
                                        auto_crop, denoise_steps, seed, mask_path)
            except Exception as e:
                last_error = e
                log.exception("Try-on attempt %d failed", attempt)
                if _is_quota_error(e):
                    break  # retrying won't help
                self._client = None  # reconnect on the next attempt
        raise _friendly_error(last_error)


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "quota" in msg or "exceeded" in msg or "rate limit" in msg


def _friendly_error(e: Exception | None) -> TryOnError:
    msg = str(e).lower()
    if _is_quota_error(e):
        return TryOnError("Daily free quota reached. Add an HF_TOKEN to your .env or try again tomorrow.", 429)
    if "timeout" in msg or "timed out" in msg or isinstance(e, TimeoutError):
        return TryOnError("The free model is busy or in a queue, please try again in a minute.", 504)
    if "queue" in msg or "busy" in msg or "paused" in msg or "sleeping" in msg or "503" in msg:
        return TryOnError("The free model is busy or in a queue, please try again in a minute.", 503)
    return TryOnError("The try-on service failed. The free Space may be down; please try again in a minute.", 502)
