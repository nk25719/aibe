import React from "react";
import {
  askTechnicalQuestion,
  getDocument,
  getDocumentIngestionStatus,
  listDocuments,
  updateDocumentVersionState,
  uploadTechnicalDocument,
} from "../api";

const TYPES = [
  "service_manual",
  "user_manual",
  "parts_catalog",
  "technical_bulletin",
  "field_modification",
  "safety_notice",
  "eol_notice",
  "eosl_notice",
  "replacement_notice",
  "installation_manual",
  "maintenance_procedure",
  "training_material",
  "other",
];

const STATUSES = ["", "current", "superseded", "withdrawn", "draft"];

export default function TechnicalLibrary() {
  const [filters, setFilters] = React.useState({ q: "", manufacturer: "", model: "", document_type: "", lifecycle_status: "", revision: "" });
  const [documents, setDocuments] = React.useState([]);
  const [selected, setSelected] = React.useState(null);
  const [qa, setQa] = React.useState({ question: "", manufacturer: "", model: "", include_historical: false });
  const [answer, setAnswer] = React.useState(null);
  const [apiKey, setApiKey] = React.useState("");
  const [file, setFile] = React.useState(null);
  const [upload, setUpload] = React.useState({ title: "", manufacturer: "", equipment_model: "", document_type: "service_manual", document_number: "", revision: "", source_url: "", verification_status: "unverified", lifecycle_status: "draft", uploaded_by: "" });
  const [status, setStatus] = React.useState("");
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const payload = await listDocuments({ ...filters, limit: 50 });
      setDocuments(payload.documents || []);
      if (!selected && payload.documents?.[0]) await selectDocument(payload.documents[0].id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function selectDocument(id) {
    setError("");
    try {
      const [metadata, ingest] = await Promise.all([getDocument(id), getDocumentIngestionStatus(id)]);
      setSelected(metadata.document);
      setStatus(ingest.ingestion_status);
    } catch (err) {
      setError(err.message);
    }
  }

  React.useEffect(() => {
    refresh();
  }, []);

  async function submitSearch(event) {
    event.preventDefault();
    await refresh();
  }

  async function ask(event) {
    event.preventDefault();
    setError("");
    setAnswer(null);
    try {
      setAnswer(await askTechnicalQuestion(qa));
    } catch (err) {
      setError(err.message);
    }
  }

  async function submitUpload(event) {
    event.preventDefault();
    if (!apiKey || !file) {
      setError("Enter the admin API key and select a PDF.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await uploadTechnicalDocument(apiKey, file, upload);
      await refresh();
      await selectDocument(result.document_id);
      setStatus(result.status);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function mark(versionId, statusName) {
    if (!apiKey) {
      setError("Enter the admin API key before changing document state.");
      return;
    }
    try {
      const result = await updateDocumentVersionState(apiKey, versionId, { status: statusName, actor: upload.uploaded_by || "service-engineer" });
      setSelected(result.document);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="library-workbench">
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Technical Library</h2>
            <p className="muted">Evidence-first technical documents with preserved versions.</p>
          </div>
          <button className="primary" onClick={refresh} disabled={loading}>{loading ? "Loading" : "Refresh"}</button>
        </div>
        {error ? <div className="error">{error}</div> : null}
        <form onSubmit={submitSearch} className="case-form">
          <input value={filters.q} onChange={(event) => setFilters({ ...filters, q: event.target.value })} placeholder="title or document number" />
          <div className="form-grid">
            <input value={filters.manufacturer} onChange={(event) => setFilters({ ...filters, manufacturer: event.target.value })} placeholder="manufacturer" />
            <input value={filters.model} onChange={(event) => setFilters({ ...filters, model: event.target.value })} placeholder="model" />
            <select value={filters.document_type} onChange={(event) => setFilters({ ...filters, document_type: event.target.value })}>
              <option value="">Any type</option>
              {TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
            <select value={filters.lifecycle_status} onChange={(event) => setFilters({ ...filters, lifecycle_status: event.target.value })}>
              {STATUSES.map((item) => <option key={item || "any"} value={item}>{item || "Any status"}</option>)}
            </select>
            <input value={filters.revision} onChange={(event) => setFilters({ ...filters, revision: event.target.value })} placeholder="revision" />
          </div>
          <button type="submit">Search</button>
        </form>
        <div className="issue-list library-list">
          {documents.length ? documents.map((doc) => (
            <button key={doc.id} className="issue-button" aria-pressed={selected?.id === doc.id} onClick={() => selectDocument(doc.id)}>
              <strong>{doc.title}</strong>
              <span>{doc.document_number || "No document number"} · {doc.document_type}</span>
              <span>{doc.manufacturer || "Unknown manufacturer"} {doc.equipment_model || ""}</span>
              <span className={`pill ${doc.conflicting_current_revisions ? "warn" : doc.current_version_id ? "ok" : ""}`}>{doc.conflicting_current_revisions ? "conflict" : doc.current_version_id ? "current" : "no current"}</span>
            </button>
          )) : <p className="empty">No documents match this filter.</p>}
        </div>
      </section>

      <section className="panel library-detail">
        {selected ? (
          <>
            <div className="candidate-head">
              <div>
                <h2>{selected.title}</h2>
                <p className="muted">{selected.document_number || "No document number"} · {selected.document_type}</p>
              </div>
              <span className={`pill ${status === "ready" ? "ok" : "warn"}`}>{status || selected.ingestion_status || "unknown"}</span>
            </div>
            <dl className="details">
              <div><dt>Manufacturer</dt><dd>{selected.manufacturer || "Unknown"}</dd></div>
              <div><dt>Model</dt><dd>{selected.equipment_model || "Unscoped"}</dd></div>
              <div><dt>Verification</dt><dd>{selected.verification_status}</dd></div>
              <div><dt>Source</dt><dd>{selected.source_url || "No source URL"}</dd></div>
            </dl>
            {selected.conflicting_current_revisions ? <div className="error">Multiple current revisions exist. Review before using this document as authority.</div> : null}
            <h3>Version History</h3>
            <div className="version-list">
              {selected.versions.map((version) => (
                <article className="run-row" key={version.id}>
                  <strong>Rev {version.revision}</strong>
                  <span className={`pill ${version.lifecycle_status === "current" ? "ok" : version.lifecycle_status === "withdrawn" ? "warn" : ""}`}>{version.lifecycle_status}</span>
                  <span>{version.original_filename || "no file name"}</span>
                  <span>{version.effective_at || "no effective date"}</span>
                  <button type="button" onClick={() => mark(version.id, "verified")}>Verify</button>
                  <button type="button" onClick={() => mark(version.id, "current")}>Current</button>
                  <button type="button" onClick={() => mark(version.id, "withdrawn")}>Withdraw</button>
                </article>
              ))}
            </div>
          </>
        ) : <p className="empty">Select a document to inspect metadata and versions.</p>}

        <form onSubmit={ask} className="qa-panel">
          <h3>Technical Question</h3>
          <textarea value={qa.question} onChange={(event) => setQa({ ...qa, question: event.target.value })} rows="3" placeholder="Ask about an error code, part number, or procedure." />
          <div className="form-grid">
            <input value={qa.manufacturer} onChange={(event) => setQa({ ...qa, manufacturer: event.target.value })} placeholder="manufacturer" />
            <input value={qa.model} onChange={(event) => setQa({ ...qa, model: event.target.value })} placeholder="model" />
          </div>
          <label className="check-row">
            <input type="checkbox" checked={qa.include_historical} onChange={(event) => setQa({ ...qa, include_historical: event.target.checked })} />
            Include historical revisions
          </label>
          <button type="submit">Ask</button>
        </form>
        {answer ? (
          <section className="evidence">
            <h3>Answer</h3>
            <p>{answer.answer}</p>
            {answer.missing_information?.length ? <div className="notice">Missing: {answer.missing_information.join(", ")}</div> : null}
            {answer.conflicts?.length ? <div className="error">{answer.conflicts.map((item) => item.type || item.detail).join(", ")}</div> : null}
            {answer.evidence?.length ? answer.evidence.map((item, index) => (
              <article className="audit-panel" key={`${item.document_version_id}-${item.page_number}-${index}`}>
                <strong>{item.title || item.document_title} rev {item.revision}</strong>
                <p>Page {item.page_number} · {item.section_heading || "section not detected"} · score {item.retrieval_score}</p>
                <p>{item.excerpt || item.extracted_fact}</p>
                <span className={`pill ${item.is_current ? "ok" : "warn"}`}>{item.lifecycle_status}</span>
              </article>
            )) : <p className="empty">No supporting evidence found.</p>}
          </section>
        ) : null}

        <form onSubmit={submitUpload} className="upload-panel">
          <h3>Protected Upload</h3>
          <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="AIBE_API_KEY" autoComplete="off" />
          <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <div className="form-grid">
            <input required value={upload.title} onChange={(event) => setUpload({ ...upload, title: event.target.value })} placeholder="title" />
            <input required value={upload.manufacturer} onChange={(event) => setUpload({ ...upload, manufacturer: event.target.value })} placeholder="manufacturer" />
            <input value={upload.equipment_model} onChange={(event) => setUpload({ ...upload, equipment_model: event.target.value })} placeholder="model" />
            <select value={upload.document_type} onChange={(event) => setUpload({ ...upload, document_type: event.target.value })}>
              {TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
            <input value={upload.document_number} onChange={(event) => setUpload({ ...upload, document_number: event.target.value })} placeholder="document number" />
            <input required value={upload.revision} onChange={(event) => setUpload({ ...upload, revision: event.target.value })} placeholder="revision" />
            <select value={upload.lifecycle_status} onChange={(event) => setUpload({ ...upload, lifecycle_status: event.target.value })}>
              {STATUSES.filter(Boolean).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <input value={upload.source_url} onChange={(event) => setUpload({ ...upload, source_url: event.target.value })} placeholder="source URL" />
          </div>
          <button className="primary" type="submit" disabled={loading}>{loading ? "Uploading" : "Upload PDF"}</button>
        </form>
      </section>
    </main>
  );
}
