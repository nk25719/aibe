const BASE = (import.meta.env.VITE_API_BASE || "http://127.0.0.1:8080").replace(/\/+$/,"");

async function requestJson(url, options) {
  let payload = null;
  let text = "";
  const r = await fetch(url, options);
  try {
    text = await r.text();
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { ok: false, error: "malformed_response", detail: text || "Backend returned non-JSON response." };
  }
  if (!r.ok) {
    const message = payload?.detail || payload?.error || `Request failed with ${r.status}`;
    throw new Error(Array.isArray(message) ? "Validation error" : String(message));
  }
  return payload;
}

export async function apiHealth() {
  return requestJson(`${BASE}/api/health`, { cache: "no-store" });
}

export async function matchImage(file, top_k=5) {
  const fd = new FormData();
  fd.append("file", file);
  return requestJson(`${BASE}/api/match-image?top_k=${top_k}`, { method: "POST", body: fd });
}

export async function getCatalog() {
  return requestJson(`${BASE}/api/catalog`, { cache: "no-store" });
}

export async function createIdentificationCase(payload) {
  const fd = new FormData();
  payload.files.forEach((file) => fd.append("files", file));
  ["manufacturer", "equipment_family", "equipment_model", "description", "visible_markings", "component_location", "opened_by"].forEach((key) => {
    if (payload[key]) fd.append(key, payload[key]);
  });
  return requestJson(`${BASE}/api/identification/cases?top_k=${payload.top_k || 5}`, { method: "POST", body: fd });
}

export async function actOnCandidate(caseId, candidateId, action, user, notes) {
  return requestJson(`${BASE}/api/identification/cases/${caseId}/candidates/${candidateId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, user, notes }),
  });
}

export async function searchParts(q, limit=20, filters = {}) {
  const params = new URLSearchParams({ q, limit: String(limit) });
  ["manufacturer", "equipment_family", "equipment_model"].forEach((key) => {
    if (filters[key]) params.set(key, filters[key]);
  });
  if (filters.enable_legacy_fallback) params.set("enable_legacy_fallback", "true");
  return requestJson(`${BASE}/api/search?${params}`, { cache: "no-store" });
}

function adminHeaders(apiKey, extra = {}) {
  return { ...extra, "X-AIBE-API-Key": apiKey };
}

export async function getImportRuns(apiKey) {
  return requestJson(`${BASE}/api/admin/import-runs`, { cache: "no-store", headers: adminHeaders(apiKey) });
}

export async function getDataQualityIssues(apiKey, filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.issue_type) params.set("issue_type", filters.issue_type);
  if (filters.manufacturer) params.set("manufacturer", filters.manufacturer);
  if (filters.equipment_model) params.set("equipment_model", filters.equipment_model);
  if (filters.source_import_id) params.set("source_import_id", filters.source_import_id);
  const suffix = params.toString() ? `?${params}` : "";
  return requestJson(`${BASE}/api/admin/data-quality/issues${suffix}`, { cache: "no-store", headers: adminHeaders(apiKey) });
}

export async function getDataQualitySummary(apiKey) {
  return requestJson(`${BASE}/api/admin/data-quality/summary`, { cache: "no-store", headers: adminHeaders(apiKey) });
}

export async function resolveDataQualityIssue(apiKey, issueId, payload) {
  return requestJson(`${BASE}/api/admin/data-quality/issues/${issueId}/resolve`, {
    method: "POST",
    headers: adminHeaders(apiKey, { "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

export async function exportDataQualityIssues(apiKey, filters = {}) {
  const params = new URLSearchParams({ format: "csv" });
  if (filters.status) params.set("status", filters.status);
  const r = await fetch(`${BASE}/api/admin/data-quality/issues/export?${params}`, {
    cache: "no-store",
    headers: adminHeaders(apiKey),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(text || `Request failed with ${r.status}`);
  return text;
}
