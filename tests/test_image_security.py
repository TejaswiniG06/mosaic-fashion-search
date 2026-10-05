import asyncio
import base64
import io
import socket

import httpx
import pytest
from PIL import Image

from services.embedding.image_security import decode_base64, decode_image, load_image_bytes


def png(size=(8, 8)):
    out = io.BytesIO()
    Image.new("RGB", size).save(out, format="PNG")
    return out.getvalue()


def test_pixel_limits_and_valid_image():
    assert decode_image(png(), 64).size == (8, 8)
    with pytest.raises(ValueError):
        decode_image(png(), 63)
    with pytest.raises(Exception):
        decode_image(b"not an image")


def test_base64_limits_before_and_after_decoding():
    data = png()
    assert decode_base64(base64.b64encode(data).decode(), len(data)) == data
    with pytest.raises(ValueError):
        decode_base64(base64.b64encode(data).decode(), len(data) - 1)
    with pytest.raises(ValueError):
        decode_base64("!invalid!", 100)


@pytest.mark.asyncio
async def test_local_traversal_absolute_path_and_byte_limit(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    (root / "ok.png").write_bytes(png())
    outside = tmp_path / "secret.png"
    outside.write_bytes(png())
    async with httpx.AsyncClient() as client:
        async def load(ref, limit=1000):
            return await load_image_bytes(ref, root, limit, [], client)
        assert await load("local://ok.png") == png()
        assert await load(str(root / "ok.png")) == png()
        assert await load("local://../secret.png") is None
        assert await load(str(outside)) is None
        assert await load("local://ok.png", 1) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://cdn.example/image.png", "https://evil.example/image.png",
                                  "https://user:pass@cdn.example/image.png", "https://cdn.example:8443/image.png"])
async def test_disallowed_urls_never_connect(url, tmp_path):
    def deny(request):
        pytest.fail("blocked URL reached transport")
    async with httpx.AsyncClient(transport=httpx.MockTransport(deny)) as client:
        assert await load_image_bytes(url, tmp_path, 1000, ["cdn.example"], client) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["169.254.169.254"], ["::1"], ["10.0.0.1"],
                                        ["93.184.216.34", "192.168.1.1"]])
async def test_private_and_mixed_dns_answers_never_connect(addresses, monkeypatch, tmp_path):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    def deny(request):
        pytest.fail("private destination reached transport")
    async with httpx.AsyncClient(transport=httpx.MockTransport(deny)) as client:
        assert await load_image_bytes("https://cdn.example/a", tmp_path, 1000, ["cdn.example"], client) is None


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"a" * 65536
        yield b"b" * 65536


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ok", "redirect", "declared_large", "stream_large", "compressed"])
async def test_public_connection_is_pinned_and_bounded(mode, monkeypatch, tmp_path):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "cdn.example"
        assert request.extensions["sni_hostname"] == "cdn.example"
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        if mode == "declared_large":
            return httpx.Response(200, headers={"content-length": "999999"})
        if mode == "compressed":
            return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Chunks())
        if mode == "stream_large":
            return httpx.Response(200, stream=Chunks())
        return httpx.Response(200, content=png())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await load_image_bytes("https://cdn.example/a", tmp_path, 1000, ["cdn.example"], client)
        assert result == (png() if mode == "ok" else None)
        assert len(calls) == 1
