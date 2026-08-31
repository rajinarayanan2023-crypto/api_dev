import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_current_active_user
from app.core.config import get_settings
from app.core.exceptions import PayloadTooLargeError, UnsupportedMediaTypeError
from app.schemas.upload import UploadOut

settings = get_settings()
router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(get_current_active_user)])

# Bills are photos of paper receipts/invoices, occasionally a scanned PDF —
# nothing else is a legitimate use of this endpoint.
_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/pdf",
}
_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "application/pdf": ".pdf",
}


@router.post("", response_model=UploadOut)
async def upload_file(file: UploadFile = File(...)) -> UploadOut:
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError(
            "Only JPEG/PNG/WEBP/HEIC images and PDFs are accepted for bill uploads."
        )

    max_bytes = settings.upload_max_size_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise PayloadTooLargeError(f"File exceeds the {settings.upload_max_size_mb}MB limit.")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    extension = _EXTENSION_BY_CONTENT_TYPE[content_type]
    stored_name = f"{uuid.uuid4().hex}{extension}"
    (upload_dir / stored_name).write_bytes(content)

    return UploadOut(file_name=file.filename or stored_name, file_url=f"/uploads/{stored_name}")
