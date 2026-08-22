import React, { useState } from "react";
import { searchParts } from "../api";

export default function PartSearch(){
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");

  async function onSubmit(e){
    e.preventDefault();
    setError("");
    try {
      const r = await searchParts(q, 30);
      setRows(r.results || []);
    } catch (err) {
      setRows([]);
      setError(err.message);
    }
  }

  return (
    <div className="card">
      <h2>Part Search (SQLite)</h2>
      <form onSubmit={onSubmit} role="search">
        <label htmlFor="q">Query</label>
        <input id="q" name="q" value={q} onChange={e=>setQ(e.target.value)} placeholder="e.g. bearing, 1009-3172-000, brand" />
        <button type="submit" style={{marginTop:8}}>Search</button>
      </form>
      {error && <div className="error" role="alert">{error}</div>}

      {rows.length ? (
        <ul className="grid">
          {rows.map((r,i)=>(
            <li key={i} className="card">
              {r.part_number && <div><strong>{r.part_number}</strong></div>}
              {r.description && <div>{r.description}</div>}
              {r.equipment1 && <div style={{opacity:0.7}}>Equipment: {r.equipment1}</div>}
              {r.brand && <div style={{opacity:0.7}}>Brand: {r.brand}</div>}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
