import io, os, json
from pathlib import Path
from typing import List, Dict

import numpy as np
from fastapi import FastAPI, UploadFile, File, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

import torch
from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
from dotenv import load_dotenv

from db import search_parts

load_dotenv()

EMBED_DIR = Path(os.getenv("EMBED_DIR","embeddings"))
CORS = [o.strip() for o in (os.getenv("CORS_ORIGINS","*")).split(",") if o.strip()]

app = FastAPI(title="AIBE Mini")
app.add_middleware(
    CORSMiddleware, allow_origins=CORS or ["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

weights = MobileNet_V3_Small_Weights.DEFAULT
_model = mobilenet_v3_small(weights=weights); _model.classifier = torch.nn.Identity(); _model.eval()
_pre = weights.transforms()

def l2norm(x: np.ndarray, axis=-1, eps=1e-12):
    n = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / (n + eps)

def embed_pil(img: Image.Image) -> np.ndarray:
    x = _pre(img.convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        v = _model(x).squeeze(0).cpu().numpy().astype("float32")
    return l2norm(v)

class Index:
    def __init__(self): self.ids=[]; self.M=None; self.dim=0; self.meta={}
    def reload(self):
        meta_path = EMBED_DIR/"metadata.json"
        if not meta_path.exists():
            self.ids=[]; self.M=None; self.dim=0; self.meta={}; return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        vf = EMBED_DIR / (meta.get("vector_file","vectors.npy"))
        if not vf.exists(): self.ids=[]; self.M=None; self.dim=0; self.meta={}; return
        M = np.load(vf)
        if M.ndim==1: M=M.reshape(1,-1)
        M = M.astype("float32"); M = l2norm(M, axis=1)
        self.ids = [ (it.get("id", f"row_{i}") if isinstance(it,dict) else f"row_{i}") for i,it in enumerate(meta.get("items", [])) ]
        if not self.ids or len(self.ids)!=M.shape[0]: self.ids=[f"row_{i}" for i in range(M.shape[0])]
        self.M = M; self.dim = int(M.shape[1]); self.meta = {str(it.get("id")):it for it in meta.get("items",[]) if isinstance(it,dict)}

    def status(self)->Dict[str,object]:
        n = 0 if self.M is None else int(self.M.shape[0])
        return {"index_size": n, "index_dim": self.dim, "embed_dir": str(EMBED_DIR.resolve())}

    def topk(self, q: np.ndarray, k: int) -> List[Dict]:
        if self.M is None or self.M.shape[0]==0: return []
        if self.M.shape[1]!=q.shape[0]: raise ValueError(f"dim mismatch: {self.M.shape[1]} vs {q.shape[0]}")
        sims = self.M @ q.astype("float32"); k = max(1, min(k, sims.size))
        idx = np.argpartition(-sims, k-1)[:k]; idx = idx[np.argsort(-sims[idx])]
        out=[]
        for i in idx:
            pid = self.ids[i]; item={"id": pid, "score": float(sims[i])}
            if pid in self.meta: item["meta"]=self.meta[pid]
            out.append(item)
        return out

_index = Index(); _index.reload()

@app.get("/api/health")
def health():
    st = _index.status(); st.update({"model":"mobilenet_v3_small","model_dim":576})
    return st

@app.post("/api/match-image")
async def match_image(file: UploadFile = File(...), top_k: int = Query(5, ge=1, le=50)):
    if (_index.M is None) or (_index.M.shape[0]==0):
        raise HTTPException(503, "Index empty. Build embeddings first.")
    raw = await file.read()
    try:
        img = Image.open(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(400, f"Invalid image: {e}")
    q = embed_pil(img)
    if _index.dim and _index.dim != q.shape[0]:
        raise HTTPException(500, f"Dim mismatch index={_index.dim} vs query={q.shape[0]}")
    matches = _index.topk(q, top_k)
    return {"ok": True, "matches": matches}

@app.get("/api/search")
def api_search(q: str = Query("", description="query"), limit: int = Query(20, ge=1, le=100)):
    hits = search_parts(q, limit)
    return {"ok": True, "count": len(hits), "results": hits}

@app.post("/api/reload")
def api_reload():
    _index.reload()
    return {"ok": True, **_index.status()}

@app.get("/")
def root():
    return JSONResponse({"service":"AIBE Mini", "try":["/api/health","/api/match-image","/api/search?q=bearing"]})
