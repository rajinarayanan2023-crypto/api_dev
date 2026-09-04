from fastapi import APIRouter, Depends

from app.api.deps import get_current_active_user
from app.core.exceptions import UnsupportedMediaTypeError
from app.core.s3 import build_key, delete_object, get_download_presigned_url, get_upload_presigned_url
from app.schemas.upload import ALLOWED_CONTENT_TYPES, DownloadUrlOut, PresignedUploadOut, PresignedUploadRequest

router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(get_current_active_user)])


# Direct-to-R2 flow: the browser PUTs the file bytes straight to the
# presigned URL below, bypassing this backend entirely for the file itself —
# this endpoint only ever handles the small JSON request/response around it.
@router.post("/presigned-upload", response_model=PresignedUploadOut)
async def create_presigned_upload(body: PresignedUploadRequest) -> PresignedUploadOut:
    content_type = body.content_type.lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError("Only JPEG/PNG/WEBP/HEIC images and PDFs are accepted for bill uploads.")
    key = build_key(body.category, body.filename)
    upload_url = get_upload_presigned_url(key, content_type)
    return PresignedUploadOut(upload_url=upload_url, key=key)


# Generated fresh on demand only — never in bulk when a list of bills is
# fetched (see FuelEntryService._serialize / CreditCustomerOut) — a
# presigned GET URL is only worth generating for a bill someone is actually
# about to open.
@router.get("/{key:path}/download-url", response_model=DownloadUrlOut)
async def create_download_url(key: str) -> DownloadUrlOut:
    return DownloadUrlOut(download_url=get_download_presigned_url(key))


@router.delete("/{key:path}", status_code=204)
async def delete_upload(key: str) -> None:
    delete_object(key)
