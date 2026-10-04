"""Cross-platform (Windows / macOS / Linux) model downloader - same result as download_models.sh.

    python scripts/download_models.py

1. multilingual-e5-small int8 ONNX (~83 MB, SHA256-verified) -> models/multilingual-e5-small/
2. OpenCLIP ViT-B/32 weights (~600 MB) -> exported to ONNX -> models/clip-vit-b32/
   (installs torch CPU + open_clip_torch + onnx into the CURRENT venv for the one-off export)
"""
import hashlib
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
E5_DIR = ROOT / "models" / "multilingual-e5-small"
CLIP_DIR = ROOT / "models" / "clip-vit-b32"
E5_URL = "https://github.com/teleport-computer/feedling-mcp/releases/download/models-e5-small-614241f6/multilingual-e5-small-614241f6-int8.tar.gz"
E5_SHA = "f964e4a46307a987ad49f46e8285d51c50199ac57933b3617be9e63546b74e17"
CLIP_URL = "https://github.com/mlfoundations/open_clip/releases/download/v0.2-weights/vit_b_32-quickgelu-laion400m_e32-46683a32.pt"


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached: {dest.name}")
        return
    print(f"  downloading {url.rsplit('/', 1)[-1]} ...")
    tmp = dest.with_suffix(dest.suffix + ".part")

    def hook(blocks, bs, total):
        if total > 0:
            print(f"\r  {min(100, blocks * bs * 100 // total):3d}%", end="", flush=True)

    urllib.request.urlretrieve(url, tmp, hook)
    print()
    tmp.replace(dest)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pip(*args: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *args])


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    E5_DIR.mkdir(parents=True, exist_ok=True)
    CLIP_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/2] multilingual-e5-small (int8 ONNX)")
    if (E5_DIR / "model_int8.onnx").exists():
        print("  already present")
    else:
        tgz = CACHE / "e5.tgz"
        download(E5_URL, tgz)
        if sha256(tgz) != E5_SHA:
            tgz.unlink()
            sys.exit("  SHA256 mismatch for e5 archive - deleted, please re-run")
        with tarfile.open(tgz) as t:
            t.extractall(E5_DIR, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        print("  ok")

    print("[2/2] OpenCLIP ViT-B/32 -> ONNX")
    if (CLIP_DIR / "visual.onnx").exists() and (CLIP_DIR / "textual.onnx").exists():
        print("  already present")
    else:
        pt = CACHE / "vitb32.pt"
        download(CLIP_URL, pt)
        print("  installing torch (CPU) + open_clip for the one-off export ...")
        try:
            pip("torch", "--index-url", "https://download.pytorch.org/whl/cpu")
        except subprocess.CalledProcessError:
            pip("torch")
        pip("open_clip_torch", "onnx", "onnxscript")
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "export_clip_onnx.py"), "--weights", str(pt), "--out", str(CLIP_DIR)])
        print("  ok (you may now `pip uninstall torch open_clip_torch` - serving does not need them)")
    print("models ready in", ROOT / "models")


if __name__ == "__main__":
    main()
