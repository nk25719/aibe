import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from fastapi import HTTPException, UploadFile, status
from PIL import Image

from app.config import settings


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
MODEL_NAME = "mobilenet_v3_small"
MODEL_DIM = 576
_model = None
_pre = None
_model_error = None


def l2norm(x: np.ndarray, axis=-1, eps=1e-12):
    n = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / (n + eps)


def get_image_model():
    global _model, _pre, _model_error
    if _model is not None and _pre is not None:
        return _model, _pre
    if _model_error is not None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Image model unavailable: {_model_error}")
    try:
        import torch
        from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
    except Exception as exc:
        _model_error = exc
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Image model unavailable: {exc}")

    weights = MobileNet_V3_Small_Weights.DEFAULT
    net = mobilenet_v3_small(weights=weights)
    net.classifier = torch.nn.Identity()
    net.eval()
    _model = SimpleNamespace(net=net, torch=torch)
    _pre = weights.transforms()
    return _model, _pre


def embed_pil(img: Image.Image) -> np.ndarray:
    model, pre = get_image_model()
    x = pre(img.convert("RGB")).unsqueeze(0)
    with model.torch.no_grad():
        v = model.net(x).squeeze(0).cpu().numpy().astype("float32")
    return l2norm(v)


class ImageIndex:
    def __init__(self, embed_dir: Path):
        self.embed_dir = embed_dir
        self.ids: list[str] = []
        self.M = None
        self.dim = 0
        self.meta: dict[str, dict[str, Any]] = {}
        self.index_metadata: dict[str, Any] = {}

    def reload(self) -> None:
        meta_path = self.embed_dir / "metadata.json"
        if not meta_path.exists():
            self.ids = []
            self.M = None
            self.dim = 0
            self.meta = {}
            self.index_metadata = {"status": "missing", "metadata_path": str(meta_path)}
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        vf = self.embed_dir / meta.get("vector_file", "vectors.npy")
        if not vf.exists():
            self.ids = []
            self.M = None
            self.dim = 0
            self.meta = {}
            self.index_metadata = {"status": "missing_vectors", "metadata_path": str(meta_path), "vector_path": str(vf)}
            return
        M = np.load(vf)
        if M.ndim == 1:
            M = M.reshape(1, -1)
        M = l2norm(M.astype("float32"), axis=1)
        items = [it for it in meta.get("items", []) if isinstance(it, dict)]
        self.ids = [(it.get("id") or f"row_{i}") for i, it in enumerate(items)]
        if not self.ids or len(self.ids) != M.shape[0]:
            self.ids = [f"row_{i}" for i in range(M.shape[0])]
        self.M = M
        self.dim = int(M.shape[1])
        self.meta = {str(it.get("id")): it for it in items if it.get("id")}
        self.index_metadata = {
            "status": "ready",
            "model": meta.get("model", MODEL_NAME),
            "model_version": meta.get("model_version"),
            "generated_at": meta.get("generated_at"),
            "count": int(M.shape[0]),
            "stale": meta.get("model") not in (None, MODEL_NAME) or int(meta.get("dim", self.dim)) != self.dim,
        }

    def status(self) -> dict[str, Any]:
        n = 0 if self.M is None else int(self.M.shape[0])
        return {
            "index_size": n,
            "index_dim": self.dim,
            "embed_dir": str(self.embed_dir),
            "model": MODEL_NAME,
            "model_dim": MODEL_DIM,
            **self.index_metadata,
        }

    def topk(self, q: np.ndarray, k: int) -> list[dict[str, Any]]:
        if self.M is None or self.M.shape[0] == 0:
            return []
        if self.M.shape[1] != q.shape[0]:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Dim mismatch index={self.M.shape[1]} vs query={q.shape[0]}")
        sims = self.M @ q.astype("float32")
        k = max(1, min(k, sims.size))
        idx = np.argpartition(-sims, k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        out = []
        for i in idx:
            pid = self.ids[i]
            item = {"id": pid, "score": float(sims[i]), "status": "candidate"}
            if pid in self.meta:
                item["meta"] = self.meta[pid]
            out.append(item)
        return out


image_index = ImageIndex(settings.embed_dir)
image_index.reload()


async def read_validated_image_upload(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported image MIME type: {file.content_type}")
    raw = await file.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Uploaded image is too large.")
    try:
        Image.open(io.BytesIO(raw)).verify()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid image: {exc}")
    return raw

