const BASE = (import.meta.env.VITE_API_BASE || "http://127.0.0.1:8080").replace(/\/+$/,"");

export async function apiHealth() {
  const r = await fetch(`${BASE}/api/health`, { cache: "no-store" });
  return r.json();
}

export async function matchImage(file, top_k=5) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${BASE}/api/match-image?top_k=${top_k}`, { method: "POST", body: fd });
  return r.json();
}

export async function searchParts(q, limit=20) {
  const r = await fetch(`${BASE}/api/search?q=${encodeURIComponent(q)}&limit=${limit}`, { cache: "no-store" });
  return r.json();
}
