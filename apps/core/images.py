"""Safe image handling for every upload: allow-list, Pillow verify, size limit, re-encode, strip EXIF."""

import io
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.deconstruct import deconstructible
from PIL import Image, ImageOps

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
MAX_PIXELS = 40_000_000


def validate_image(upload):
    if upload.size > settings.MAX_IMAGE_UPLOAD_BYTES:
        raise ValidationError("Image is too large (max 5 MB).")
    try:
        upload.seek(0)
        img = Image.open(upload)
        img.verify()
        upload.seek(0)
        img = Image.open(upload)
    except Exception as exc:
        raise ValidationError("That file is not a valid image.") from exc
    if img.format not in ALLOWED_FORMATS:
        raise ValidationError("Only JPG, PNG, WebP or GIF images are allowed.")
    if img.width * img.height > MAX_PIXELS:
        raise ValidationError("Image dimensions are too large.")
    upload.seek(0)
    return upload


def reencode(upload, max_side=1600, fmt="WEBP", quality=82) -> ContentFile:
    """Return a new file: EXIF stripped, orientation applied, resized, random name."""
    validate_image(upload)
    img = Image.open(upload)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, fmt, quality=quality, method=4)  # no exif passed -> stripped
    ext = {"WEBP": "webp", "JPEG": "jpg", "PNG": "png", "AVIF": "avif"}[fmt]
    return ContentFile(out.getvalue(), name=f"{uuid.uuid4().hex}.{ext}")


@deconstructible
class RandomUploadPath:
    """upload_to callable that ignores the client filename and uses a random name."""

    def __init__(self, prefix):
        self.prefix = prefix

    def __call__(self, instance, filename):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webp"
        if ext not in {"webp", "jpg", "jpeg", "png", "gif", "avif"}:
            ext = "webp"
        return f"{self.prefix}/{uuid.uuid4().hex}.{ext}"

    def __eq__(self, other):
        return isinstance(other, RandomUploadPath) and other.prefix == self.prefix
