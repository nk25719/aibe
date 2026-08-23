import React, { useEffect, useState } from "react";
import { getCatalog, searchParts } from "../api";

export default function PartSearch(){
  const [q, setQ] = useState("");
  const [catalog, setCatalog] = useState({ manufacturers: [], equipment_models: [], equipment_families: [] });
  const [filters, setFilters] = useState({ manufacturer: "", equipment_model: "", enable_legacy_fallback: false });
  const [rows, setRows] = useState([]);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getCatalog().then(setCatalog).catch(() => {});
  }, []);

  async function onSubmit(e){
    e.preventDefault();
    setError("");
    try {
      const r = await searchParts(q, 30, filters);
      setRows(r.results || []);
      setSource(r.source || "");
    } catch (err) {
      setRows([]);
      setError(err.message);
    }
  }

  return (
    <div className="card">
      <h2>Part Search</h2>
      <form onSubmit={onSubmit} role="search">
        <label htmlFor="q">Query</label>
        <input id="q" name="q" value={q} onChange={e=>setQ(e.target.value)} placeholder="e.g. bearing, 1009-3172-000, brand" />
        <div className="form-grid">
          <label>Manufacturer
            <select value={filters.manufacturer} onChange={(e)=>setFilters((current)=>({ ...current, manufacturer: e.target.value }))}>
              <option value="">Any</option>
              {catalog.manufacturers.map((item)=><option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label>Model
            <select value={filters.equipment_model} onChange={(e)=>setFilters((current)=>({ ...current, equipment_model: e.target.value }))}>
              <option value="">Any</option>
              {catalog.equipment_models.map((item)=><option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
        </div>
        <label className="check-row">
          <input type="checkbox" checked={filters.enable_legacy_fallback} onChange={(e)=>setFilters((current)=>({ ...current, enable_legacy_fallback: e.target.checked }))} />
          Enable labeled legacy fallback
        </label>
        <button type="submit" style={{marginTop:8}}>Search</button>
      </form>
      {error && <div className="error" role="alert">{error}</div>}
      {source && <div className={source === "legacy_fallback" ? "error" : "notice"}>{source === "legacy_fallback" ? "Legacy fallback results are shown." : "Normalized catalog results are shown."}</div>}

      {rows.length ? (
        <ul className="grid">
          {rows.map((r,i)=>(
            <li key={i} className="card">
              {r.part_number && <div><strong>{r.part_number}</strong></div>}
              {r.description && <div>{r.description}</div>}
              <div style={{opacity:0.7}}>Catalog ID: {r.normalized_part_id || "legacy only"}</div>
              {r.manufacturer || r.brand ? <div style={{opacity:0.7}}>Manufacturer: {r.manufacturer || r.brand}</div> : null}
              {r.equipment1 && <div style={{opacity:0.7}}>Compatible: {r.equipment1}</div>}
              {r.aliases?.length ? <div style={{opacity:0.7}}>Aliases: {r.aliases.map((a)=>a.alias).join(", ")}</div> : null}
              <div><span className="pill">{r.verification_status || "unknown"}</span> {r.legacy_fallback_used ? <span className="pill warn">legacy fallback</span> : <span className="pill ok">normalized</span>}</div>
              {r.supersession?.is_superseded ? <div className="notice">Replacement: {r.supersession.replacements.map((p)=>p.part_number).join(", ")}</div> : null}
              {r.contradicting_evidence?.length ? <div className="error">{r.contradicting_evidence.map((item)=>item.detail).join(" ")}</div> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
