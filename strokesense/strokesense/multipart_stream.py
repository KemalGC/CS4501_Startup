"""Bounded streaming multipart parser for a local-only upload endpoint."""
from email.parser import BytesHeaderParser
from email import policy

CHUNK = 64 * 1024
MAX_HEADERS = 8192


class MultipartError(ValueError):
    pass


def receive(stream, length, boundary, video_file, max_video):
    """Write video bytes incrementally; retain only small text fields in memory."""
    if not 1 <= len(boundary) <= 70 or any(c < 33 or c > 126 for c in boundary):
        raise MultipartError("invalid boundary")
    delim = b"\r\n--" + boundary
    remaining = length
    buffer = bytearray()

    def fill(minimum):
        nonlocal remaining
        while len(buffer) < minimum and remaining:
            chunk = stream.read(min(CHUNK, remaining))
            if not chunk:
                raise MultipartError("truncated request")
            buffer.extend(chunk)
            remaining -= len(chunk)

    def take_until(marker, cap):
        while True:
            pos = buffer.find(marker)
            if pos >= 0:
                if pos > cap:
                    raise MultipartError("field too large")
                result = bytes(buffer[:pos])
                del buffer[:pos + len(marker)]
                return result
            if len(buffer) > cap + len(marker):
                raise MultipartError("field too large")
            if not remaining:
                raise MultipartError("missing delimiter")
            fill(len(buffer) + 1)

    fill(len(boundary) + 4)
    prefix = b"--" + boundary + b"\r\n"
    if not buffer.startswith(prefix):
        raise MultipartError("invalid opening boundary")
    del buffer[:len(prefix)]
    fields = {}
    filename = None
    while True:
        raw_headers = take_until(b"\r\n\r\n", MAX_HEADERS)
        headers = BytesHeaderParser(policy=policy.default).parsebytes(
            raw_headers + b"\r\n\r\n")
        if headers.get_content_disposition() != "form-data":
            raise MultipartError("invalid part disposition")
        name = headers.get_param("name", header="content-disposition")
        if name not in {"csrf", "permission", "provenance", "camera", "analyze", "video"} or name in fields:
            raise MultipartError("invalid or duplicate field")
        fields[name] = None
        if name == "video":
            filename = headers.get_filename()
            if not filename:
                raise MultipartError("missing filename")
            sink = video_file
            limit = max_video
        else:
            sink = None
            limit = 1024
            value = bytearray()
        count = 0
        while True:
            search = 0
            pos = -1
            while True:
                candidate = buffer.find(delim, search)
                if candidate < 0:
                    break
                if len(buffer) < candidate + len(delim) + 2 and remaining:
                    fill(candidate + len(delim) + 2)
                if bytes(buffer[candidate + len(delim):candidate + len(delim) + 2]) in (b"--", b"\r\n"):
                    pos = candidate
                    break
                search = candidate + 1
            if pos >= 0:
                portion = buffer[:pos]
                count += len(portion)
                if count > limit:
                    raise MultipartError("part exceeds size limit")
                if sink is None:
                    value.extend(portion)
                else:
                    sink.write(portion)
                del buffer[:pos + len(delim)]
                break
            keep = len(delim) + 2
            n = max(0, len(buffer) - keep)
            if n:
                count += n
                if count > limit:
                    raise MultipartError("part exceeds size limit")
                if sink is None:
                    value.extend(buffer[:n])
                else:
                    sink.write(bytes(buffer[:n]))
                del buffer[:n]
            if not remaining:
                raise MultipartError("missing closing boundary")
            fill(len(buffer) + 1)
        if sink is None:
            fields[name] = bytes(value).decode("utf-8")
        else:
            fields[name] = count
        fill(2)
        ending = bytes(buffer[:2])
        del buffer[:2]
        if ending == b"--":
            fill(2)
            if bytes(buffer) not in (b"", b"\r\n") or remaining:
                raise MultipartError("trailing request bytes")
            break
        if ending != b"\r\n":
            raise MultipartError("invalid boundary terminator")
    return fields, filename
