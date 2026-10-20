"""Load native media libraries only for features that need them."""


class MediaUnavailable(Exception):
    pass


def image_backend():
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except (ImportError, OSError) as error:
        raise MediaUnavailable(
            "Image and PDF uploads are unavailable because the server cannot load its image library. "
            "You can still add typed student work. Ask the server administrator to check the "
            "installation or application-control policy."
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


def upload_capabilities():
    try:
        image_backend()
    except MediaUnavailable as error:
        return {"images": False, "pdf": False, "message": str(error)}
    try:
        pdf_backend()
    except MediaUnavailable as error:
        return {"images": True, "pdf": False, "message": str(error)}
    return {"images": True, "pdf": True, "message": ""}
