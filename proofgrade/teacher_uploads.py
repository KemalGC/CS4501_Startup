"""Bounded image/PDF intake. Only normalized PNG pages are retained and served."""

import base64
import binascii
import io
import math
import warnings

from fastapi import Depends, HTTPException, Response
from pydantic import Field

from proofgrade.feedback import ProviderUnavailable
from proofgrade.image_pages import BrowserImageInput, rgb_png
from proofgrade.teacher_api import record_data
from proofgrade.teacher_models import RevisionInput, SubmissionInput
from proofgrade.teacher_media import MediaUnavailable, image_backend, pdf_backend, pdf_uploads_enabled
from proofgrade.teacher_store import RevisionConflict

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 5
MAX_PIXELS = 20_000_000
MAX_SIDE = 1800


class UploadInput(SubmissionInput):
    file_base64: str = Field(min_length=1, max_length=12 * 1024 * 1024)


def normalized_png(image):
    Image, _, _ = image_backend()
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def render_upload(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Upload a valid image or scanned PDF.") from error
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Each upload must be at most 8 MiB.")
    if raw.startswith(b"%PDF-"):
        if not pdf_uploads_enabled():
            raise MediaUnavailable("PDF uploads are turned off. Upload a JPG/PNG photo in the teacher workspace instead.")
        image_backend()
        pdfium = pdf_backend()
        try:
            with pdfium.PdfDocument(raw) as pdf:
                if not 1 <= len(pdf) <= MAX_PAGES:
                    raise ValueError("Use a PDF with 1–5 pages.")
                pages = []
                for index in range(len(pdf)):
                    page = pdf[index]
                    try:
                        width, height = page.get_size()
                        if not all(math.isfinite(x) and 1 <= x <= 20000 for x in (width, height)):
                            raise ValueError("PDF page dimensions are unsupported.")
                        bitmap = page.render(scale=min(2, MAX_SIDE / max(width, height)))
                        try:
                            pages.append(normalized_png(bitmap.to_pil()))
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                return pages
        except pdfium.PdfiumError as error:
            raise ValueError("Could not read this PDF. Use an unencrypted scanned worksheet.") from error
    Image, ImageOps, UnidentifiedImageError = image_backend()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in ("PNG", "JPEG"):
                    raise ValueError("Use a JPG, PNG, or scanned PDF.")
                if original.width * original.height > MAX_PIXELS or getattr(original, "n_frames", 1) != 1:
                    raise ValueError("Use a single image of at most 20 megapixels.")
                original.load()
                return [normalized_png(ImageOps.exif_transpose(original))]
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Could not read this image. Use a JPG, PNG, or scanned PDF.") from error


def add_upload_routes(router, teacher, store, model):
    @router.post("/assignments/{assignment_id}/image-uploads", status_code=201)
    def upload_pixels(assignment_id: str, body: BrowserImageInput, owner=Depends(teacher)):
        store.assignment(owner, assignment_id)
        page = rgb_png(body.width, body.height, body.pixels_base64)
        return store.create_submission(owner, assignment_id, body.student_code, [page])

    @router.post("/assignments/{assignment_id}/uploads", status_code=201)
    def upload(assignment_id: str, body: UploadInput, owner=Depends(teacher)):
        store.assignment(owner, assignment_id)
        try:
            pages = render_upload(body.file_base64)
        except MediaUnavailable as error:
            raise HTTPException(503, str(error)) from error
        return store.create_submission(owner, assignment_id, body.student_code, pages)

    @router.get("/submissions/{submission_id}/pages/{number}")
    def page(submission_id: str, number: int, owner=Depends(teacher)):
        return Response(store.page(owner, submission_id, number), media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    @router.post("/submissions/{submission_id}/extract")
    def extract(submission_id: str, body: RevisionInput, owner=Depends(teacher)):
        record = store.submission(owner, submission_id)
        if body.revision != record["revision"]:
            raise RevisionConflict()
        if not record["page_count"]:
            raise HTTPException(400, "This response has no uploaded pages.")
        if model is None:
            raise HTTPException(503, "AI transcription is not configured. You can enter the work manually beside the source.")
        assignment = store.assignment(owner, record["assignment_id"])
        pages = [store.page(owner, submission_id, i) for i in range(1, record["page_count"] + 1)]
        try:
            extraction = model.extract(assignment, pages)
        except ProviderUnavailable as error:
            raise HTTPException(503, str(error)) from error
        data = record_data(record) | {"answers": extraction["answers"], "results": [], "extraction": "openai",
                                     "message": "AI draft — compare every equation with the source, then confirm or correct it."}
        data.pop("approved_at", None)
        return store.update_submission(owner, submission_id, body.revision, "transcription_draft", data, "ai_transcribed")


class BoundedRequestBody:
    """Enforce a byte cap even for chunked requests before JSON parsing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        limit = 12 * 1024 * 1024 if scope["path"].endswith(("/uploads", "/image-uploads")) else 256 * 1024
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                from starlette.responses import JSONResponse
                return await JSONResponse({"detail": "Request is too large."}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
