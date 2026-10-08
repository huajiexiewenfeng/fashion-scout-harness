import hashlib
import shutil
import warnings
from PIL import Image, UnidentifiedImageError
from fashion_scout.domain import ScoutError


def disk_gate(paths, reserve, floor):
    for path in {paths.root, paths.media}:
        if shutil.disk_usage(path).free < reserve + floor:
            raise ScoutError("DISK_RESERVE", "Configured free-space reserve would be crossed")


def validate_image(path, max_bytes, max_pixels):
    if path.stat().st_size > max_bytes:
        raise ScoutError("IMAGE_BYTES_LIMIT", "Image exceeds byte limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                fmt = image.format
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ScoutError("IMAGE_PIXEL_LIMIT", "Image exceeds pixel limit")
                if fmt not in ("JPEG", "PNG", "WEBP", "GIF"):
                    raise ScoutError("IMAGE_FORMAT", "Unsupported gallery image format")
                if getattr(image, "n_frames", 1) != 1:
                    raise ScoutError("IMAGE_ANIMATION", "Animated gallery image is not supported")
                image.verify()
            with Image.open(path) as image:
                image.load()
    except PermissionError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ScoutError("IMAGE_INVALID", "Image could not be verified and decoded") from exc
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": sha, "bytes": path.stat().st_size, "format": fmt, "width": width, "height": height}


def validate_archived_cover(path, asset, max_bytes, max_pixels):
    """Match a cover to bytes already decoded by Archive, without decoding again.

    Known Archive metadata plus the same SHA proves these are the previously
    decoded bytes. The header also rejects forged/non-image metadata. Legacy
    assets without decoder metadata take the full validation path. No result is
    cached across requests, so file changes never depend on a TTL or timestamp.
    """
    before = path.stat()
    if before.st_size != asset["bytes"] or before.st_size > max_bytes:
        raise ScoutError("IMAGE_INVALID", "Archived image size differs")
    known = (asset["format"] in ("JPEG", "PNG", "WEBP", "GIF")
             and asset["width"] and asset["height"])
    if not known:
        actual = validate_image(path, max_bytes, max_pixels)
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    width, height = image.size
                    fmt = image.format
                    if (width <= 0 or height <= 0 or width * height > max_pixels
                            or getattr(image, "n_frames", 1) != 1):
                        raise ScoutError("IMAGE_INVALID", "Archived image header differs")
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            actual = {"sha256": sha, "bytes": before.st_size, "format": fmt, "width": width, "height": height}
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ScoutError("IMAGE_INVALID", "Archived cover is not readable") from exc
    after = path.stat()
    signature = lambda s: (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)
    if (signature(before) != signature(after) or actual["sha256"] != asset["sha256"]
            or any(asset[k] not in (None, 0, "UNKNOWN", actual[k]) for k in ("format", "width", "height"))):
        raise ScoutError("IMAGE_INVALID", "Archived cover integrity differs")
    return actual
