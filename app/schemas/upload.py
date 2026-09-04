from pydantic import BaseModel

# Bills are photos of paper receipts/invoices, occasionally a scanned PDF —
# nothing else is a legitimate use of the uploads endpoint.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/pdf",
}


class PresignedUploadRequest(BaseModel):
    filename: str
    content_type: str
    # Groups keys by feature in the bucket (e.g. "fuel-entry-bills",
    # "credit-customer-bills") — purely organizational, not security.
    category: str


class PresignedUploadOut(BaseModel):
    upload_url: str
    key: str


class DownloadUrlOut(BaseModel):
    download_url: str
