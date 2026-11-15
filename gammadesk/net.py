"""HTTP for the free JSON source: urllib only, so the GitHub runner needs no extra packages."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable, Mapping

Opener = Callable[..., object]
RETRY_CODES = frozenset({429, 500, 502, 503, 504})
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.6 Safari/605.1.15"
)


class FetchError(RuntimeError):
    pass


def num(value: object) -> float | None:
    """'1,234' -> 1234.0; '$185.30' -> 185.3; '--', 'N/A', '' or None -> None."""
    if value is None or isinstance(value, bool):
        return None
    s = str(value).replace(",", "").replace("$", "").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    return x if x == x and abs(x) != float("inf") else None


def _decode(raw: bytes, encoding: str) -> bytes:
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def get_json(
    url: str, headers: Mapping[str, str], opener: Opener, timeout: float, retries: int
) -> object:
    req = urllib.request.Request(url, headers=dict(headers))
    for attempt in range(retries + 1):
        try:
            with opener(req, timeout=timeout) as resp:
                info = getattr(resp, "headers", None)
                encoding = (info.get("Content-Encoding") or "").lower() if info else ""
                return json.loads(_decode(resp.read(), encoding).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_CODES and attempt < retries:
                time.sleep(2 + 2 * attempt)
                continue
            raise FetchError(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, zlib.error) as exc:
            if attempt < retries:
                time.sleep(2 + 2 * attempt)
                continue
            raise FetchError(type(exc).__name__) from None
    raise FetchError("unreachable")
