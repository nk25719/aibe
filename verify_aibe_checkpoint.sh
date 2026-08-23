#!/usr/bin/env bash

set -uo pipefail

REPO_PATH="${1:-/Users/naghamkheir/Repos/aibe}"

if [[ ! -d "$REPO_PATH/.git" ]]; then
  echo "ERROR: Git repository not found at: $REPO_PATH" >&2
  echo "Usage: $0 [path-to-aibe-repository]" >&2
  exit 2
fi

cd "$REPO_PATH" || exit 2

REPORT_DIR="$REPO_PATH/checkpoint-reports"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
REPORT_FILE="$REPORT_DIR/aibe-checkpoint-$TIMESTAMP.txt"
mkdir -p "$REPORT_DIR"

FAILURES=0

run_check() {
  local title="$1"
  shift

  echo
  echo "===== $title ====="

  if "$@"; then
    echo "PASS: $title"
  else
    local status=$?
    echo "FAIL: $title (exit $status)"
    FAILURES=$((FAILURES + 1))
  fi
}

run_shell_check() {
  local title="$1"
  local command="$2"

  echo
  echo "===== $title ====="

  if bash -o pipefail -c "$command"; then
    echo "PASS: $title"
  else
    local status=$?
    echo "FAIL: $title (exit $status)"
    FAILURES=$((FAILURES + 1))
  fi
}

find_python() {
  if [[ -x "$REPO_PATH/backend/.venv/bin/python" ]]; then
    printf '%s\n' "$REPO_PATH/backend/.venv/bin/python"
  elif [[ -x "$REPO_PATH/.venv/bin/python" ]]; then
    printf '%s\n' "$REPO_PATH/.venv/bin/python"
  else
    return 1
  fi
}

exec > >(tee "$REPORT_FILE") 2>&1

{
  echo "AIBE checkpoint verification"
  echo "Generated: $(date)"
  echo "Repository: $REPO_PATH"

  run_check "Git status" git status
  run_check "Branches" git branch -vv
  run_check "Recent history" git log --oneline --decorate --graph -12
  run_check "Diff summary" git diff --stat
  run_check "Diff whitespace validation" git diff --check
  run_check "Changed files" git diff --name-status

  if [[ -d backend/alembic/versions ]]; then
    run_check "Migration changes" git diff -- backend/alembic/versions
  fi

  for path in \
    backend/app/db/models.py \
    backend/app/routers/documents.py \
    backend/app/services/documents.py
  do
    if [[ -e "$path" ]]; then
      run_check "Diff: $path" git diff -- "$path"
    fi
  done

  if PYTHON_BIN="$(find_python)"; then
    run_check "Backend tests" "$PYTHON_BIN" -m pytest

    if [[ -f backend/evaluate_documents.py ]]; then
      run_check "Document evaluation" "$PYTHON_BIN" backend/evaluate_documents.py
    fi

    if [[ -f backend/manage.py ]]; then
      run_check "Catalog audit" "$PYTHON_BIN" backend/manage.py audit-catalog
    fi

    if [[ -f backend/reconcile_catalog.py ]]; then
      run_check "Catalog reconciliation" "$PYTHON_BIN" backend/reconcile_catalog.py
    fi
  else
    echo
    echo "FAIL: Python virtual environment not found."
    echo "Expected backend/.venv/bin/python or .venv/bin/python."
    FAILURES=$((FAILURES + 1))
  fi

  if [[ -f frontend/package.json ]]; then
    run_shell_check "Frontend tests" "cd frontend && npm test"
    run_shell_check "Frontend production build" "cd frontend && npm run build"
  else
    echo
    echo "FAIL: frontend/package.json not found."
    FAILURES=$((FAILURES + 1))
  fi

  echo
  echo "===== CHECKPOINT SUMMARY ====="
  echo "Failures: $FAILURES"
  echo "Report: $REPORT_FILE"

  if (( FAILURES == 0 )); then
    echo "RESULT: PASS"
  else
    echo "RESULT: FAIL"
  fi
}

if (( FAILURES > 0 )); then
  exit 1
fi

exit 0