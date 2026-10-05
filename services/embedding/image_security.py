"""Bounded image loading. Remote connections are pinned to validated public IPs."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import io
import socket
import warnings
from pathlib import Path

import httpx
from PIL import Image


def decode_image(data: bytes, max_pixels: int = 20_000_000) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > max_pixels:
            raise ValueError("image pixel limit exceeded")
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("unsupported image format")
        image.load()
        return image


def decode_base64(value: str, max_bytes: int) -> bytes:
    encoded = value.split(",", 1)[-1]
    if len(encoded) > 4 * ((max_bytes + 2) // 3):
        raise ValueError("image byte limit exceeded")
    data = base64.b64decode(encoded, validate=True)
    if len(data) > max_bytes:
        raise ValueError("image byte limit exceeded")
    return data


def _read_local(path: Path, root: Path, limit: int) -> bytes:
    path, root = path.resolve(), root.resolve()
    if root not in path.parents:
        raise ValueError("image outside image root")
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("image byte limit exceeded")
    return data


async def load_image_bytes(ref: str, root: Path, max_bytes: int, allowed_hosts: list[str],
                           client: httpx.AsyncClient) -> bytes | None:
    try:
        if ref.startswith("local://"):
            return await asyncio.to_thread(_read_local, root / ref[8:], root, max_bytes)
        if not ref.startswith(("https://", "http://")):
            return await asyncio.to_thread(_read_local, Path(ref), root, max_bytes)
        url = httpx.URL(ref)
        if (url.scheme != "https" or url.port not in (None, 443) or url.userinfo
                or url.host.lower() not in {h.lower() for h in allowed_hosts}):
            return None
        answers = await asyncio.get_running_loop().getaddrinfo(url.host, 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            return None
        # Avoid a second DNS lookup (DNS rebinding); preserve TLS certificate validation for the original host.
        pinned = url.copy_with(host=addresses[0])
        async with client.stream("GET", pinned, headers={"Host": url.host, "Accept-Encoding": "identity"},
                                 extensions={"sni_hostname": url.host}, follow_redirects=False) as response:
            if response.status_code != 200:
                return None
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                return None
            if int(response.headers.get("content-length", "0")) > max_bytes:
                return None
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > max_bytes:
                    return None
            return bytes(data)
    except (OSError, ValueError, httpx.HTTPError):
        return None
