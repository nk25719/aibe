import React from "react";
import { exportDataQualityIssues, getDataQualityIssues, getImportRuns, resolveDataQualityIssue } from "../api";

const STATUS_OPTIONS = ["open", "under_review", "resolved", "accepted_as_distinct", "merged", "ignored_with_reason"];

function JsonBlock({ value }) {
  if (!value) return <p className="muted">No values recorded.</p>;
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

export default function DataReview() {
  const [apiKey, setApiKey] = React.useState("");
  const [runs, setRuns] = React.useState([]);
  const [issues, setIssues] = React.useState([]);
  const [status, setStatus] = React.useState("open");
  const [selectedId, setSelectedId] = React.useState(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [resolution, setResolution] = React.useState({
    status: "accepted_as_distinct",
    resolution_selected: "accepted_as_distinct",
    resolved_by: "",
    resolution_notes: "",
  });

  const selected = issues.find((issue) => issue.id === selectedId) || issues[0];

  async function refresh() {
    if (!apiKey) {
      setError("Enter the configured AIBE_API_KEY to use protected data-review endpoints.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [runPayload, issuePayload] = await Promise.all([
        getImportRuns(apiKey),
        getDataQualityIssues(apiKey, { status }),
      ]);
      setRuns(runPayload.runs);
      setIssues(issuePayload.issues);
      setSelectedId(issuePayload.issues[0]?.id ?? null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    if (apiKey) refresh();
  }, [status]);

  async function submitResolution(event) {
    event.preventDefault();
    if (!selected) return;
    setLoading(true);
    setError("");
    try {
      await resolveDataQualityIssue(apiKey, selected.id, {
        ...resolution,
        evidence: { reviewed_in: "AIBE data review UI" },
      });
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function downloadExport() {
    if (!apiKey) {
      setError("Enter the configured AIBE_API_KEY before exporting issues.");
      return;
    }
    try {
      const csv = await exportDataQualityIssues(apiKey, { status });
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `aibe-data-quality-${status}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="review-workbench">
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Data Review</h2>
            <p className="muted">Protected data-steward workflow. Production role management is still required.</p>
          </div>
          <button className="primary" onClick={refresh} disabled={loading}>{loading ? "Loading" : "Refresh"}</button>
        </div>
        {error ? <div className="error">{error}</div> : null}
        <label>
          Admin API key
          <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" />
        </label>
        <label>
          Issue status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            {STATUS_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <div className="summary-table">
          <h3>Import Runs</h3>
          {runs.length ? runs.map((run) => (
            <article key={run.id} className="run-row">
              <strong>Run #{run.id}</strong>
              <span>{run.source_name}</span>
              <span>inserted {run.inserted}</span>
              <span>updated {run.updated}</span>
              <span>skipped {run.skipped}</span>
              <span>ambiguous {run.ambiguous}</span>
              <span>rejected {run.rejected}</span>
              <span>changed {run.changed}</span>
            </article>
          )) : <p className="empty">No import runs loaded.</p>}
        </div>
        <button className="export-link" onClick={downloadExport}>Export filtered issues as CSV</button>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Issues</h2>
            <p className="muted">Source data, normalized data, AI suggestions, and admin resolutions are separated.</p>
          </div>
          <span className="pill">{issues.length} loaded</span>
        </div>
        <div className="issue-grid">
          <div className="issue-list">
            {issues.length ? issues.map((issue) => (
              <button
                key={issue.id}
                className="issue-button"
                aria-pressed={selected?.id === issue.id}
                onClick={() => setSelectedId(issue.id)}
              >
                <strong>{issue.issue_type}</strong>
                <span>{issue.entity_type} #{issue.entity_id || "source"}</span>
                <span className={`pill ${issue.severity === "high" ? "warn" : ""}`}>{issue.severity}</span>
              </button>
            )) : <p className="empty">No issues match this filter.</p>}
          </div>

          {selected ? (
            <article className="issue-detail">
              <div className="candidate-head">
                <div>
                  <h3>Issue #{selected.id}</h3>
                  <p>{selected.suggested_resolution}</p>
                </div>
                <span className="pill warn">{selected.status}</span>
              </div>
              <div className="comparison-grid">
                <section>
                  <h4>Source Data</h4>
                  <JsonBlock value={selected.source_row_values || selected.original_values} />
                </section>
                <section>
                  <h4>Normalized Data</h4>
                  <JsonBlock value={selected.normalized_values} />
                </section>
                <section>
                  <h4>Conflicting Values</h4>
                  <JsonBlock value={selected.conflicting_values} />
                </section>
                <section>
                  <h4>Linked Evidence</h4>
                  <JsonBlock value={selected.evidence} />
                </section>
              </div>
              <section className="audit-panel">
                <h4>Audit History</h4>
                <JsonBlock value={selected.audit_history} />
              </section>
              <form className="resolution-form" onSubmit={submitResolution}>
                <label>
                  Resolution status
                  <select value={resolution.status} onChange={(event) => setResolution({ ...resolution, status: event.target.value, resolution_selected: event.target.value })}>
                    {STATUS_OPTIONS.filter((item) => item !== "open").map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </label>
                <label>
                  Resolved by
                  <input value={resolution.resolved_by} onChange={(event) => setResolution({ ...resolution, resolved_by: event.target.value })} required />
                </label>
                <label>
                  Resolution note
                  <textarea value={resolution.resolution_notes} onChange={(event) => setResolution({ ...resolution, resolution_notes: event.target.value })} required rows={3} />
                </label>
                <button className="primary" disabled={loading || !resolution.resolved_by || !resolution.resolution_notes}>
                  Record Review Decision
                </button>
              </form>
            </article>
          ) : null}
        </div>
      </section>
    </div>
  );
}
