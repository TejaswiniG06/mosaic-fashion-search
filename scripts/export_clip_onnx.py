"""One-off export of OpenCLIP ViT-B/32 image & text towers to ONNX (serving then needs only onnxruntime).
Verifies the ONNX outputs against PyTorch (cosine must be > 0.9999)."""
import argparse
import os
import shutil

import numpy as np
import open_clip
import torch

ap = argparse.ArgumentParser()
ap.add_argument("--weights", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
model, _, _ = open_clip.create_model_and_transforms("ViT-B-32-quickgelu", pretrained=a.weights)
model.eval()
tok = open_clip.get_tokenizer("ViT-B-32-quickgelu")


class V(torch.nn.Module):
    def __init__(s, m):
        super().__init__()
        s.m = m

    def forward(s, x):
        return s.m.encode_image(x)


class T(torch.nn.Module):
    def __init__(s, m):
        super().__init__()
        s.m = m

    def forward(s, x):
        return s.m.encode_text(x)


img, txt = torch.randn(1, 3, 224, 224), tok(["a red cotton dress"])
for name, mod, inp, iname in [("visual.onnx", V(model), img, "pixel_values"), ("textual.onnx", T(model), txt, "input_ids")]:
    torch.onnx.export(mod, (inp,), os.path.join(a.out, name), input_names=[iname], output_names=["embeds"],
                      dynamic_axes={iname: {0: "batch"}, "embeds": {0: "batch"}}, opset_version=17, dynamo=False)
import open_clip.tokenizer as t  # noqa: E402

shutil.copy(os.path.join(os.path.dirname(t.__file__), "bpe_simple_vocab_16e6.txt.gz"), a.out)
import onnxruntime as ort  # noqa: E402

with torch.no_grad():
    ref = model.encode_image(img).numpy()
got = ort.InferenceSession(os.path.join(a.out, "visual.onnx")).run(None, {"pixel_values": img.numpy()})[0]
cos = float(np.dot((ref / np.linalg.norm(ref)).ravel(), (got / np.linalg.norm(got)).ravel()))
print(f"export ok; torch-vs-onnx cosine = {cos:.6f}")
assert cos > 0.9999
