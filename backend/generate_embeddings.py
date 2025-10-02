import os, hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image

import torch
from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

IMAGES_DIR = Path(os.getenv("IMAGES_DIR","images"))
OUT_DIR    = Path(os.getenv("EMBED_DIR","embeddings"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

def l2norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v) + 1e-12
    return v / n

@torch.inference_mode()
def embed(p: Path):
    weights = MobileNet_V3_Small_Weights.DEFAULT
    model = mobilenet_v3_small(weights=weights); model.classifier = torch.nn.Identity(); model.eval()
    pre = weights.transforms()
    x = pre(Image.open(p).convert("RGB")).unsqueeze(0)
    v = model(x).squeeze(0).cpu().numpy().astype("float32")
    return l2norm(v)

def main():
    exts = {".jpg",".jpeg",".png",".webp",".bmp"}
    files = sorted([p for p in IMAGES_DIR.rglob("*") if p.suffix.lower() in exts])
    if not files: raise SystemExit(f"No images found under {IMAGES_DIR.resolve()}")

    vecs=[]; items=[]
    for i,p in enumerate(files):
        v = embed(p); vecs.append(v)
        rel = p.relative_to(IMAGES_DIR).as_posix()
        items.append({
            "id": p.stem,
            "filename": rel,
            "preview_path": f"images/{rel}",
            "index": i,
            "sha1": hashlib.sha1(p.read_bytes()).hexdigest()[:12],
        })

    V = np.stack(vecs).astype("float32")
    np.save(OUT_DIR/"vectors.npy", V)
    meta = {"vector_file":"vectors.npy","dim": int(V.shape[1]),"count": int(V.shape[0]),"items": items}
    (OUT_DIR/"metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[OK] wrote {V.shape} -> {OUT_DIR/'vectors.npy'} & metadata.json")

if __name__=="__main__":
    main()
