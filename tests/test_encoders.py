from pathlib import Path

import numpy as np
import pytest

from mosaic_common.config import get_settings

S = get_settings()
pytestmark = pytest.mark.skipif(not (S.clip_model_dir / "visual.onnx").exists(), reason="models not downloaded")


def test_clip_tokenizer_matches_open_clip_ids():
    from services.embedding.encoders import ClipTokenizer
    tok = ClipTokenizer(S.clip_model_dir / "bpe_simple_vocab_16e6.txt.gz")
    assert tok(["a red cotton dress"])[0, :6].tolist() == [49406, 320, 736, 7050, 2595, 49407]


def test_clip_colour_discrimination():
    from PIL import Image
    from ingestion.render_images import render
    from services.embedding.encoders import ClipEncoder
    c = ClipEncoder(S.clip_model_dir)
    imgs = [render("dress", "red", "solid"), render("dress", "blue", "solid")]
    I = c.encode_images(imgs)
    T = c.encode_text(["a photo of a red dress", "a photo of a blue dress"])
    sims = T @ I.T
    assert sims[0, 0] > sims[0, 1] and sims[1, 1] > sims[1, 0]


def test_e5_multilingual_alignment():
    from services.embedding.encoders import TextEncoder
    e = TextEncoder(S.text_model_dir, S.text_model_file)
    q = e.encode(["शादी के लिए लाल साड़ी"], "query")
    p = e.encode(["Red silk saree for weddings", "Black running shoes for the gym"], "passage")
    s = (q @ p.T)[0]
    assert s[0] > s[1]
    assert np.allclose(np.linalg.norm(p, axis=1), 1, atol=1e-4)
