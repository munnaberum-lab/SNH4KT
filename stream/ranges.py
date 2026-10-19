"""HTTP Range parsing and Telegram chunk math. Pure, no third-party imports."""
import math

CHUNK = 1024 * 1024  # Telegram reads in 1 MiB chunks aligned to 1 MiB


class RangeError(Exception):
    pass


def parse_range(header, size):
    """Single range only. Returns (start, end_inclusive, partial). Raises RangeError (-> 416)."""
    if size <= 0:
        raise RangeError("empty file")
    if not header:
        return 0, size - 1, False
    h = header.strip().lower()
    if not h.startswith("bytes=") or "," in h:
        raise RangeError("unsupported range")
    spec = h[6:].strip()
    if "-" not in spec:
        raise RangeError("bad range")
    a, b = spec.split("-", 1)
    try:
        if a == "":
            n = int(b)
            if n <= 0:
                raise RangeError("bad suffix")
            start, end = max(size - n, 0), size - 1
        else:
            start = int(a)
            end = int(b) if b != "" else size - 1
    except ValueError:
        raise RangeError("bad range")
    end = min(end, size - 1)
    if start < 0 or start >= size or end < start:
        raise RangeError("unsatisfiable")
    return start, end, True


def chunk_plan(start, end, chunk=CHUNK):
    """offset (aligned), first_cut, last_cut, part_count for bytes start..end inclusive."""
    offset = start - (start % chunk)
    first_cut = start - offset
    last_cut = (end % chunk) + 1
    part_count = math.ceil((end + 1) / chunk) - offset // chunk
    return offset, first_cut, last_cut, part_count


def slice_part(chunk, index, part_count, first_cut, last_cut):
    """Trim the first and last chunk of a range. index is 1-based."""
    if part_count == 1:
        return chunk[first_cut:last_cut]
    if index == 1:
        return chunk[first_cut:]
    if index == part_count:
        return chunk[:last_cut]
    return chunk


def content_disposition(name, attachment):
    from urllib.parse import quote
    kind = "attachment" if attachment else "inline"
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in name) or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


BROWSER_MIMES = ("video/mp4", "video/webm")


def is_playable(mime, size=0):
    """Files browsers can decode. Over 2 GB is marked not playable."""
    return (mime or "").lower() in BROWSER_MIMES and (size or 0) <= 2 * 1024 ** 3
