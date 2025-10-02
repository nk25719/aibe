import React, { useState, useRef } from "react";
import { apiHealth, matchImage } from "../api";

export default function ImageIdentify(){
  const [file, setFile] = useState(null);
  const [topK, setTopK] = useState(5);
  const [resp, setResp] = useState(null);
  const [status, setStatus] = useState(null);
  const liveRef = useRef(null);

  React.useEffect(() => { apiHealth().then(setStatus).catch(()=>{}); }, []);

  async function onSubmit(e){
    e.preventDefault();
    setResp(null);
    if(!file) return;
    const r = await matchImage(file, topK);
    setResp(r);
    queueMicrotask(()=> liveRef.current?.focus());
  }

  return (
    <div className="card">
      <div style={{display:"flex", alignItems:"center", gap:8}}>
        <h2 style={{margin:0}}>Identify by Image</h2>
        <span title={status ? `index: ${status.index_size}, dim: ${status.index_dim}` : "no status"}
              style={{fontSize:12, padding:"2px 6px", borderRadius:6, background: status?.index_size>0 ? "#10b981" : "#ef4444", color:"#fff"}}>
          {status?.index_size>0 ? "Index: OK" : "Index: Empty"}
        </span>
      </div>

      <form onSubmit={onSubmit}>
        <label htmlFor="img-file">Image file</label>
        <input id="img-file" name="file" type="file" accept="image/*" onChange={e=>setFile(e.target.files?.[0]||null)} />
        <label htmlFor="topk">Top-K</label>
        <input id="topk" name="top_k" type="number" min="1" max="50" value={topK} onChange={e=>setTopK(Number(e.target.value)||5)} />
        <button type="submit" style={{marginTop:8}}>Find matches</button>
      </form>

      <h3 tabIndex={-1} ref={liveRef} style={{outline:"none"}}>Results</h3>
      <div aria-live="polite" aria-atomic="true" className="sr-only"></div>

      {resp?.matches?.length ? (
        <ul className="grid">
          {resp.matches.map((m,i)=>(
            <li key={i} className="card">
              <div style={{fontSize:12, opacity:0.7}}>score: {typeof m.score==="number"? m.score.toFixed(3): "—"}</div>
              {m.meta?.preview_path && <img src={m.meta.preview_path} alt={m.meta?.filename || m.id} />}
              <div style={{marginTop:6}}><strong>{m.id}</strong></div>
              {m.meta?.filename && <div>{m.meta.filename}</div>}
            </li>
          ))}
        </ul>
      ) : resp ? <div className="card">No matches</div> : null}
    </div>
  );
}
