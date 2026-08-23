import argparse
import json

from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.services.import_parts import import_parts_spreadsheet


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Initialized foundation database.")


def import_parts() -> None:
    with SessionLocal() as db:
        report = import_parts_spreadsheet(db)
    print(json.dumps(report.as_dict(), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="AIBE backend management commands")
    parser.add_argument("command", choices=["init-db", "import-parts"])
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
    elif args.command == "import-parts":
        import_parts()


if __name__ == "__main__":
    main()
