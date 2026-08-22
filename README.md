# AIBE Foundation

AIBE means Artificially Intelligent Biomedical Engineer. This repository is an early foundation for a biomedical-equipment service assistant. The current scope is intentionally narrow: preserve the existing text search and image-similarity prototype while adding a safer data model, import path, API structure, and setup instructions.

Do not treat image similarity or text search as verified medical-equipment identification. AI candidates are only candidates until a qualified biomedical engineer confirms them using compatible equipment context and source evidence.

## Current Architecture

- `backend/`: FastAPI application, legacy SQLite search DB, normalized SQLAlchemy foundation, Alembic config, importer, and image embedding tooling.
- `frontend/`: React/Vite UI with Identify and Search tabs.
- `backend/parts.db`: existing flat prototype search database with FTS.
- `backend/AIBE Parts list.xlsx`: source spreadsheet used by both the legacy loader and the new idempotent importer.
- `backend/images/`: sample part images used by the image embedding prototype.

## Data Flow

1. Spreadsheet rows are preserved as raw values.
2. `python manage.py import-parts` imports them into the normalized foundation DB without overwriting the source spreadsheet or legacy DB.
3. Existing `/api/search` still reads the flat `parts.db` FTS workflow for compatibility.
4. `/api/match-image` uses generated MobileNetV3 embeddings when available and returns candidate matches only.
5. `/api/identification/cases` creates a guided identification case with multiple images, manufacturer/model context, optional text, OCR when available, candidate ranking, evidence, and follow-up questions.
6. Engineer confirm/reject/uncertain actions are stored as controlled confirmation events and audit entries.
7. Controlled document ingestion stores source metadata, checksums, page chunks, extraction status, and version history.
8. Source-grounded QA and troubleshooting retrieve cited document excerpts and log reasoning inputs.
9. Administrative mutation endpoints require `AIBE_API_KEY`.

## Local Setup

Backend:

```bash
cd /Users/naghamkheir/Repos/aibe/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py init-db
python manage.py import-parts
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

Frontend, in another terminal:

```bash
cd /Users/naghamkheir/Repos/aibe/frontend
npm install
cp .env.example .env
npm run dev
```

Open `http://localhost:5173`.

Useful checks:

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/ready
curl "http://127.0.0.1:8080/api/search?q=filter&limit=3"
```

## Identification Workflow

The Identify workspace supports multiple image upload with preview/removal, required manufacturer context, optional equipment family/model, description, visible markings or partial part number, and component location/function.

Candidate retrieval combines supported structured fields, legacy text search signals, optional OCR text, and image similarity when embeddings exist. Every result remains an AI candidate until a qualified engineer confirms it. Rejected and uncertain actions are retained for audit and future evaluation.

Each candidate can show the official part number, description, manufacturer, compatible equipment text available from the current data, supported evidence, match factors, contradictions, confidence level, verification status, and external commercial lookup status. Price and availability are intentionally not core technical truth.

## Image Embeddings

Generate embeddings only from preserved local images:

```bash
cd backend
source .venv/bin/activate
python generate_embeddings.py
```

Generated embeddings are ignored by git. The metadata records model name, model version, generation time, count, and dimension. Missing embeddings produce a clear `503` from the image endpoint.

OCR is opportunistic. If `pytesseract` and a system OCR engine are not installed, the identification workflow continues and reports that no OCR text was extracted.

## Evaluation

A tiny non-confidential fixture lives at `backend/eval_fixture.json`.

Run:

```bash
cd backend
source .venv/bin/activate
python evaluate_identification.py
```

The output reports top-1 and top-k retrieval on that fixture only. It is a smoke evaluation, not evidence of production accuracy.

Current fixture result from the local development run:

```text
cases: 3
top-1: 1.0
top-k: 1.0
```

Because the fixture is tiny and partly text-driven, this should only be read as a regression check.

## Technical Documents

Document ingestion is controlled by `AIBE_API_KEY`:

```bash
curl -X POST http://127.0.0.1:8080/api/documents/ingest \
  -H "Content-Type: application/json" \
  -H "X-AIBE-API-Key: $AIBE_API_KEY" \
  -d '{
    "path": "tests/fixtures/ge_monitor_service_manual_rev_b.txt",
    "manufacturer": "GE Healthcare",
    "equipment_model": "TM-100",
    "document_type": "service_manual",
    "title": "TM-100 Service Manual",
    "document_number": "TM100-SVC",
    "revision": "B",
    "published_at": "2026-01-01",
    "effective_at": "2026-01-01",
    "language": "en",
    "source": "internal fixture",
    "access_classification": "non_confidential_fixture"
  }'
```

Supported ingestion fields include manufacturer, equipment family/model, document type, title, document number, revision, publication/effective dates, language, source, access classification, checksum, duplicate detection, page extraction, extraction method, figure/table references when detected, ingestion status, and errors. PDF text extraction uses `pypdf`; OCR fallback is recorded as unavailable unless a future OCR worker is configured.

Technical QA:

```bash
curl -X POST http://127.0.0.1:8080/api/documents/qa \
  -H "Content-Type: application/json" \
  -d '{"manufacturer":"GE Healthcare","model":"TM-100","question":"ERR-101 flow sensor voltage"}'
```

Answers separate extracted evidence from inference. AIBE will not invent procedures, error codes, part numbers, or citations when evidence is missing.

## Troubleshooting

Troubleshooting cases are created at `/api/troubleshooting/cases`. Inputs include manufacturer, model, serial/configuration/version, error code, symptom, measurements, operating context, attempted actions, service history, and reviewer.

Responses include problem restatement, missing information, ranked possible causes, evidence, safe next checks, required tools/measurements, relevant documents and bulletins, candidate parts, stop/escalation conditions, and a service-report draft. AIBE is decision support only; qualified review is required before diagnostics or repair.

## Document Evaluation

Small non-confidential fixtures live in `backend/tests/fixtures` and `backend/eval_documents.json`.

Run:

```bash
cd backend
source .venv/bin/activate
python evaluate_documents.py
```

The evaluator reports citation accuracy, unsupported-question refusal, and troubleshooting evidence count on tiny fixtures only.

## Data Governance

- Do not ingest confidential manufacturer portal files unless access classification and storage policy are approved.
- Preserve document versions and revisions; do not overwrite historical manuals.
- Preserve warnings, prerequisites, lockout/tagout instructions, and manufacturer safety notes.
- Keep source paths, checksums, extraction status, and ingestion errors auditable.
- Separate quoted/extracted facts from AI inference.
- Do not allow feedback or troubleshooting outcomes to silently modify authoritative manufacturer data.

## Normalized Database

Default local foundation DB:

```text
backend/aibe_foundation.db
```

Override with PostgreSQL-ready configuration:

```bash
export DATABASE_URL="postgresql+psycopg://user:password@host:5432/aibe"
```

Alembic is configured in `backend/alembic.ini`. The current app also creates tables at startup for local convenience.

## ER Diagram

```mermaid
erDiagram
  manufacturers ||--o{ manufacturer_aliases : has
  manufacturers ||--o{ equipment_families : has
  manufacturers ||--o{ equipment_models : makes
  equipment_families ||--o{ equipment_models : groups
  equipment_models ||--o{ equipment_model_aliases : has
  equipment_models ||--o{ equipment_configurations : has
  parts ||--o{ part_aliases : has
  parts ||--o{ part_images : has
  parts ||--o{ part_model_compatibility : fits
  equipment_models ||--o{ part_model_compatibility : uses
  equipment_configurations ||--o{ part_model_compatibility : constrains
  parts ||--o{ part_supersessions : old_part
  parts ||--o{ part_supersessions : new_part
  documents ||--o{ document_versions : has
  document_versions ||--o{ document_chunks : contains
  document_versions ||--o{ document_links : links
  technical_bulletins ||--o{ document_links : cited_by
  lifecycle_notices ||--o{ document_links : cited_by
  identification_cases ||--o{ identification_inputs : receives
  identification_cases ||--o{ identification_candidates : proposes
  identification_candidates ||--o{ identification_confirmations : confirmed_by_engineer
  source_evidence ||--o{ part_model_compatibility : supports
  source_evidence ||--o{ identification_candidates : supports
```

## Audit Notes

- Existing DB schema: flat `parts` table with columns `row_id`, `col`, `part_number`, `alternate_pn`, `description`, `equipment1`, `brand`, `eq_category`, `natural_description`, `note`, plus FTS indexes.
- Spreadsheet columns: `#`, `part number`, `Alternate PN`, `Description`, `Equipment1`, `Brand`, `EQ category`, `Natural Description`, `Note`.
- Existing endpoints preserved or replaced: `/`, `/api/health`, `/api/search`, `/api/match-image`. Added `/api/ready`, protected `/api/admin/import-parts`, and protected `/api/reload`.
- Identification endpoints added: `/api/catalog`, `/api/identification/cases`, and `/api/identification/cases/{case_id}/candidates/{candidate_id}/action`.
- Document/troubleshooting endpoints added: `/api/documents/ingest`, `/api/documents/qa`, and `/api/troubleshooting/cases`.
- Risks reduced: cwd-sensitive file paths, unprotected reload, backend import failure when PyTorch is unavailable, frontend non-2xx handling, missing upload validation.
- Remaining decisions: source-document ingestion policy, official manufacturer taxonomy, compatibility verification workflow, production auth model, whether legacy `parts.db` should remain tracked long-term.
- Additional unresolved decisions: document access-control model, OCR worker/runtime, redaction policy, retention policy, reviewer identity source, and approval workflow for service-report drafts.

## Verification

```bash
python -m compileall backend
pytest
cd backend && python evaluate_identification.py
cd backend && python evaluate_documents.py
cd frontend && npm test
cd frontend && npm run build
```
