import React, { useEffect, useMemo, useState } from "react";
import { actOnCandidate, apiHealth, createIdentificationCase, getCatalog } from "../api";

export default function ImageIdentify(){
  const [files, setFiles] = useState([]);
  const [catalog, setCatalog] = useState({ manufacturers: [], equipment_models: [], equipment_families: [] });
  const [status, setStatus] = useState(null);
  const [form, setForm] = useState({
    manufacturer: "",
    equipment_family: "",
    equipment_model: "",
    description: "",
    visible_markings: "",
    component_location: "",
    opened_by: "",
    top_k: 5,
  });
  const [caseResult, setCaseResult] = useState(null);
  const [actionNotes, setActionNotes] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    apiHealth().then(setStatus).catch((err) => setError(`Backend unavailable: ${err.message}`));
    getCatalog().then(setCatalog).catch(() => {});
  }, []);

  const previews = useMemo(() => files.map((file) => ({ file, url: URL.createObjectURL(file) })), [files]);

  useEffect(() => () => previews.forEach((preview) => URL.revokeObjectURL(preview.url)), [previews]);

  function updateField(key, value){
    setForm((current) => ({ ...current, [key]: value }));
  }

  function addFiles(selected){
    const incoming = Array.from(selected || []);
    setFiles((current) => [...current, ...incoming].slice(0, 6));
  }

  function removeFile(index){
    setFiles((current) => current.filter((_, i) => i !== index));
  }

  async function onSubmit(e){
    e.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    setCaseResult(null);
    try {
      const result = await createIdentificationCase({ ...form, files });
      setCaseResult(result);
      if (!result.candidates.length) {
        setError(result.message);
      }
    } catch (err) {
      setError(err.message.includes("Failed to fetch") ? "Backend unavailable or offline." : err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onAction(candidate, action){
    setError("");
    setSuccess("");
    try {
      const user = form.opened_by || "service-engineer";
      const result = await actOnCandidate(caseResult.case_id, candidate.candidate_id, action, user, actionNotes[candidate.candidate_id] || "");
      setCaseResult((current) => ({
        ...current,
        candidates: current.candidates.map((item) => item.candidate_id === candidate.candidate_id ? { ...item, verification_status: result.status } : item),
      }));
      setSuccess(`Candidate ${candidate.official_part_number || candidate.candidate_id} marked ${result.status}.`);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="workbench">
      <section className="panel context-panel">
        <div className="panel-head">
          <div>
            <h2>Part Identification Case</h2>
            <p className="muted">Candidate retrieval with engineer verification required.</p>
          </div>
          <span className={status?.image_index?.index_size > 0 ? "pill ok" : "pill warn"}>
            {status?.image_index?.index_size > 0 ? "Image index ready" : "Image index missing"}
          </span>
        </div>

        <form onSubmit={onSubmit} className="case-form">
          <div className="form-grid">
            <label>Manufacturer
              <input list="manufacturers" value={form.manufacturer} onChange={(e)=>updateField("manufacturer", e.target.value)} required />
            </label>
            <datalist id="manufacturers">{catalog.manufacturers.map((m)=><option key={m.value} value={m.value} />)}</datalist>

            <label>Equipment family
              <input list="families" value={form.equipment_family} onChange={(e)=>updateField("equipment_family", e.target.value)} />
            </label>
            <datalist id="families">{catalog.equipment_families.map((m)=><option key={m.value} value={m.value} />)}</datalist>

            <label>Equipment model
              <input list="models" value={form.equipment_model} onChange={(e)=>updateField("equipment_model", e.target.value)} />
            </label>
            <datalist id="models">{catalog.equipment_models.map((m)=><option key={m.value} value={m.value} />)}</datalist>

            <label>Engineer
              <input value={form.opened_by} onChange={(e)=>updateField("opened_by", e.target.value)} placeholder="name or initials" />
            </label>
          </div>

          <label>Description
            <textarea value={form.description} onChange={(e)=>updateField("description", e.target.value)} rows="3" />
          </label>
          <label>Visible markings or partial part number
            <textarea value={form.visible_markings} onChange={(e)=>updateField("visible_markings", e.target.value)} rows="2" />
          </label>
          <label>Component location or function
            <textarea value={form.component_location} onChange={(e)=>updateField("component_location", e.target.value)} rows="2" />
          </label>

          <label>Photos
            <input type="file" accept="image/*" multiple onChange={(e)=>addFiles(e.target.files)} />
          </label>

          {previews.length ? (
            <ul className="preview-grid">
              {previews.map((preview, index)=>(
                <li key={`${preview.file.name}-${index}`} className="preview">
                  <img src={preview.url} alt={preview.file.name} />
                  <button type="button" onClick={()=>removeFile(index)}>Remove</button>
                </li>
              ))}
            </ul>
          ) : <div className="empty">No photos selected.</div>}

          <button className="primary" disabled={busy || !files.length || !form.manufacturer}>
            {busy ? "Analyzing..." : "Find Candidates"}
          </button>
        </form>
      </section>

      <section className="panel results-panel">
        <h2>Candidate Results</h2>
        {error && <div className="error" role="alert">{error}</div>}
        {success && <div className="notice" role="status">{success}</div>}
        {!caseResult && !busy && !error && <div className="empty">Upload photos and context to start a case.</div>}
        {busy && <div className="loading">Retrieving supported candidates...</div>}

        {caseResult && (
          <>
            <div className="case-summary">
              <strong>Case #{caseResult.case_id}</strong>
              <span>{caseResult.message}</span>
            </div>
            {caseResult.ocr?.text ? <div className="notice">OCR: {caseResult.ocr.text}</div> : <div className="empty">{caseResult.ocr?.message}</div>}
            {caseResult.follow_up_questions?.length ? (
              <div className="questions">
                <h3>Follow-up Questions</h3>
                {caseResult.follow_up_questions.map((q)=><p key={q}>{q}</p>)}
              </div>
            ) : null}
            <div className="candidate-list">
              {caseResult.candidates.map((candidate)=>(
                <article className="candidate" key={candidate.candidate_id}>
                  <div className="candidate-head">
                    <div>
                      <h3>{candidate.official_part_number || "Unknown part number"}</h3>
                      <p>{candidate.part_name || candidate.official_description || "No official description available."}</p>
                    </div>
                    <span className={`pill ${candidate.confidence_level}`}>{candidate.confidence_level}</span>
                  </div>
                  <dl className="details">
                    <div><dt>Manufacturer</dt><dd>{candidate.manufacturer || "Unknown"}</dd></div>
                    <div><dt>Description</dt><dd>{candidate.official_description || "Not available"}</dd></div>
                    <div><dt>Compatible models</dt><dd>{candidate.compatible_equipment_models.join(", ") || "Not supported by current data"}</dd></div>
                    <div><dt>Supersession</dt><dd>{candidate.replacement_or_superseding_part || "No supported supersession"}</dd></div>
                    <div><dt>Verification</dt><dd>{candidate.verification_status}</dd></div>
                    <div><dt>Commercial lookup</dt><dd>{candidate.commercial_lookup_status}</dd></div>
                  </dl>
                  <section className="evidence">
                    <h4>Match Factors</h4>
                    {candidate.match_factors.length ? candidate.match_factors.map((f, i)=><p key={i}>{f.detail}</p>) : <p>No strong factor recorded.</p>}
                    <h4>Contradicting Evidence</h4>
                    {candidate.contradicting_evidence.length ? candidate.contradicting_evidence.map((f, i)=><p key={i}>{f.detail}</p>) : <p>None recorded.</p>}
                    <h4>Sources</h4>
                    {candidate.source_evidence.map((src, i)=><p key={i}>{src.source} {src.section ? `- ${src.section}` : ""}</p>)}
                  </section>
                  <div className="actions">
                    <input placeholder="engineer notes" value={actionNotes[candidate.candidate_id] || ""} onChange={(e)=>setActionNotes((n)=>({ ...n, [candidate.candidate_id]: e.target.value }))} />
                    <button type="button" onClick={()=>onAction(candidate, "confirm")}>Confirm</button>
                    <button type="button" onClick={()=>onAction(candidate, "reject")}>Reject</button>
                    <button type="button" onClick={()=>onAction(candidate, "uncertain")}>Uncertain</button>
                  </div>
                </article>
              ))}
            </div>
          </>
        )}
      </section>
    </main>
  );
}
