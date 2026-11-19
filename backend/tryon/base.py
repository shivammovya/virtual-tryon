"""Abstract interface that every try-on provider must implement."""
from abc import ABC, abstractmethod


class TryOnError(Exception):
    """A friendly, user-facing error. `status_code` is the HTTP code to return."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TryOnProvider(ABC):
    """To add a new provider (Gemini, Replicate...): subclass this in a new
    file, implement try_on(), then register it in backend/config.py."""

    @abstractmethod
    def try_on(
        self,
        person_path: str,
        garment_path: str,
        garment_desc: str,
        auto_crop: bool = False,
        denoise_steps: int = 30,
        seed: int = 42,
    ) -> str:
        """Run the try-on and return the path of the output image file.
        Raise TryOnError with a friendly message on failure."""

    # Providers that can also return / accept the garment mask override this.
    # Returns (output_image_path, masked_preview_path_or_None).
    supports_mask = False

    def try_on_with_mask(
        self,
        person_path: str,
        garment_path: str,
        garment_desc: str,
        denoise_steps: int = 30,
        seed: int = 42,
        mask_path: str | None = None,
    ) -> tuple[str, str | None]:
        """Default: no mask support - just run a normal try-on."""
        out = self.try_on(person_path, garment_path, garment_desc,
                          denoise_steps=denoise_steps, seed=seed)
        return out, None
