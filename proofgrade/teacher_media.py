"""Load native media libraries only for features that need them."""

import os


class MediaUnavailable(Exception):
    pass


def image_backend():
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except (ImportError, OSError) as error:
        raise MediaUnavailable(
            "The optional server image library is unavailable. Upload a JPG/PNG photo through "
            "the teacher workspace, which prepares images in your browser, or add typed student work."
        ) from error
    return Image, ImageOps, UnidentifiedImageError


def pdf_backend():
    try:
        import pypdfium2
    except (ImportError, OSError) as error:
        raise MediaUnavailable(
            "PDF uploads are unavailable because the server cannot load its PDF library. "
            "You can still upload JPG/PNG images or add typed student work. Ask the server "
            "administrator to check the installation or application-control policy."
        ) from error
    return pypdfium2


def pdf_uploads_enabled():
    return os.getenv("PROOFGRADE_PDF_UPLOADS", "false").lower() == "true"


def upload_capabilities():
    capabilities = {"images": True, "image_transport": "browser_rgb", "pdf": False, "message": ""}
    if not pdf_uploads_enabled():
        return capabilities  # Default startup never imports Pillow or PDFium.
    try:
        image_backend()
        pdf_backend()
    except MediaUnavailable as error:
        return capabilities | {"message": "PDF uploads are unavailable. " + str(error)}
    return capabilities | {"pdf": True}
