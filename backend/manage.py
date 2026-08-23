import argparse
import json

from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.services.catalog_audit import build_catalog_audit_report
from app.services.import_parts import import_parts_spreadsheet


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Initialized foundation database.")


def import_parts() -> None:
    with SessionLocal() as db:
        report = import_parts_spreadsheet(db)
    print(json.dumps(report.as_dict(), indent=2))


def audit_catalog(include_idempotency: bool = False, summary: bool = False) -> None:
    with SessionLocal() as db:
        report = build_catalog_audit_report(db, include_idempotency=include_idempotency)
    if summary:
        latest = report["latest_import"]
        historical = report["historical_imports"]
        catalog = report["canonical_catalog"]
        issues = report["issues"]
        print(f"Database: {report['database']['identity']}")
        print(f"Migration: {report['database']['latest_migration']}")
        print(f"Latest import spreadsheet data rows: {latest['spreadsheet_data_rows']}")
        print(f"Latest import source rows created: {latest['source_rows_created']}")
        print(f"Historical preserved source rows: {historical['total_preserved_source_rows']}")
        print(f"Canonical unique parts: {catalog['unique_parts']}")
        print(f"Aliases: {catalog['aliases']}")
        print(f"Compatibility links: {catalog['compatibility_links']}")
        print(f"Open data-quality issues: {issues['open_issues']}")
        print(f"Blocking ambiguities: {issues['blocking_ambiguity_count']}")
        print(f"Duplicate issue groups: {issues['duplicate_issue_group_count']}")
        return
    print(json.dumps(report, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="AIBE backend management commands")
    parser.add_argument("command", choices=["init-db", "import-parts", "audit-catalog"])
    parser.add_argument("--idempotency-check", action="store_true", help="Run an isolated repeated-import idempotency check.")
    parser.add_argument("--summary", action="store_true", help="Print a readable summary instead of JSON.")
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
    elif args.command == "import-parts":
        import_parts()
    elif args.command == "audit-catalog":
        audit_catalog(include_idempotency=args.idempotency_check, summary=args.summary)


if __name__ == "__main__":
    main()
