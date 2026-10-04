"""ONNX Runtime encoders (CPU, torch-free at serving time).

* TextEncoder  : intfloat/multilingual-e5-small (int8 ONNX). Asymmetric prefixes "query: " / "passage: ",
                 mean pooling + L2 norm (as specified by the model card). 100+ languages incl. Tamil & Hindi.
* ClipEncoder  : OpenCLIP ViT-B/32 (LAION-400M) image & text towers exported to ONNX. The CLIP BPE
                 tokenizer is re-implemented here (port of open_clip.SimpleTokenizer) so no torch is needed.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import io
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
import regex as re
from PIL import Image
from tokenizers import Tokenizer


def _session(path: Path, threads: int) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])


def _l2(x: np.ndarray) -> np.ndarray:
    return x / np.clip(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12, None)


def model_fingerprint(directory: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(directory.iterdir()):
        if f.is_file():
            h.update(f.name.encode())
            h.update(str(f.stat().st_size).encode())
    return h.hexdigest()[:12]


class TextEncoder:
    dim = 384

    def __init__(self, model_dir: Path, model_file: str = "model_int8.onnx", threads: int = 2, max_len: int = 256):
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_length=max_len)
        self.tok.enable_padding(pad_id=self.tok.token_to_id("<pad>") or 1, pad_token="<pad>")
        self.sess = _session(model_dir / model_file, threads)
        self.input_names = {i.name for i in self.sess.get_inputs()}
        self.version = f"e5-small-{model_fingerprint(model_dir)}"

    def encode(self, texts: list[str], kind: str = "query", batch_size: int = 32) -> np.ndarray:
        prefix = "query: " if kind == "query" else "passage: "
        out = []
        for i in range(0, len(texts), batch_size):
            enc = self.tok.encode_batch([prefix + t for t in texts[i:i + batch_size]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self.sess.run(None, feeds)[0]
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            out.append(_l2(pooled))
        return np.vstack(out).astype(np.float32) if out else np.zeros((0, self.dim), np.float32)


# ------------------------------------------------------------------ CLIP BPE tokenizer (port of open_clip)
@lru_cache()
def _bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


def _pairs(word):
    return {(a, b) for a, b in zip(word, word[1:])}


class ClipTokenizer:
    def __init__(self, bpe_path: Path, context_length: int = 77):
        self.byte_encoder = _bytes_to_unicode()
        merges = gzip.open(bpe_path).read().decode("utf-8").split("\n")[1:49152 - 256 - 2 + 1]
        merges = [tuple(m.split()) for m in merges]
        vocab = list(self.byte_encoder.values())
        vocab = vocab + [v + "</w>" for v in vocab] + ["".join(m) for m in merges] + ["<start_of_text>", "<end_of_text>"]
        self.encoder = {v: i for i, v in enumerate(vocab)}
        self.bpe_ranks = {m: i for i, m in enumerate(merges)}
        self.cache: dict[str, str] = {}
        self.pat = re.compile(r"""<start_of_text>|<end_of_text>|'s|'t|'re|'ve|'m|'ll|'d|[\p{L}]+|[\p{N}]|[^\s\p{L}\p{N}]+""", re.IGNORECASE)
        self.sot, self.eot, self.ctx = self.encoder["<start_of_text>"], self.encoder["<end_of_text>"], context_length

    def _bpe(self, token: str) -> str:
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = _pairs(word)
        if not pairs:
            return token + "</w>"
        while True:
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new, i = [], 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                except ValueError:
                    new.extend(word[i:])
                    break
                new.extend(word[i:j])
                i = j
                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    new.append(first + second)
                    i += 2
                else:
                    new.append(word[i])
                    i += 1
            word = tuple(new)
            if len(word) == 1:
                break
            pairs = _pairs(word)
        out = " ".join(word)
        self.cache[token] = out
        return out

    def encode(self, text: str) -> list[int]:
        text = " ".join(html.unescape(html.unescape(text)).strip().split()).lower()
        ids = []
        for tok in self.pat.findall(text):
            tok = "".join(self.byte_encoder[b] for b in tok.encode("utf-8"))
            ids.extend(self.encoder[t] for t in self._bpe(tok).split(" "))
        return ids

    def __call__(self, texts: list[str]) -> np.ndarray:
        arr = np.zeros((len(texts), self.ctx), dtype=np.int64)
        for i, t in enumerate(texts):
            toks = [self.sot] + self.encode(t) + [self.eot]
            if len(toks) > self.ctx:
                toks = toks[: self.ctx]
                toks[-1] = self.eot
            arr[i, : len(toks)] = toks
        return arr


MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def preprocess_image(img: Image.Image, size: int = 224) -> np.ndarray:
    img = img.convert("RGB")
    w, h = img.size
    s = size / min(w, h)
    img = img.resize((max(size, round(w * s)), max(size, round(h * s))), Image.BICUBIC)
    w, h = img.size
    left, top = (w - size) // 2, (h - size) // 2
    img = img.crop((left, top, left + size, top + size))
    x = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
    return x.transpose(2, 0, 1)


class ClipEncoder:
    dim = 512

    def __init__(self, model_dir: Path, threads: int = 2):
        self.tok = ClipTokenizer(model_dir / "bpe_simple_vocab_16e6.txt.gz")
        self.text_sess = _session(model_dir / "textual.onnx", threads)
        self.vis_sess = _session(model_dir / "visual.onnx", threads)
        self.version = f"openclip-vitb32-{model_fingerprint(model_dir)}"

    def encode_text(self, texts: list[str]) -> np.ndarray:
        return _l2(self.text_sess.run(None, {"input_ids": self.tok(texts)})[0]).astype(np.float32)

    def encode_images(self, images: list[Image.Image], batch_size: int = 16) -> np.ndarray:
        out = []
        for i in range(0, len(images), batch_size):
            x = np.stack([preprocess_image(im) for im in images[i:i + batch_size]])
            out.append(_l2(self.vis_sess.run(None, {"pixel_values": x})[0]))
        return np.vstack(out).astype(np.float32) if out else np.zeros((0, self.dim), np.float32)


def image_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img
