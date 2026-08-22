import sqlite3

from app.config import settings
from app.services.normalization import clean_text


def get_catalog_options() -> dict[str, list[dict[str, str]]]:
    manufacturers: set[str] = set()
    models: set[str] = set()
    families: set[str] = set()
    with sqlite3.connect(settings.legacy_parts_db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT DISTINCT brand, equipment1, eq_category FROM parts ORDER BY brand, equipment1"):
            brand = clean_text(row["brand"])
            model = clean_text(row["equipment1"])
            family = clean_text(row["eq_category"])
            if brand:
                manufacturers.add(brand)
            if model:
                models.add(model)
            if family:
                families.add(family)
    return {
        "manufacturers": [{"value": item, "label": item} for item in sorted(manufacturers)],
        "equipment_models": [{"value": item, "label": item} for item in sorted(models)],
        "equipment_families": [{"value": item, "label": item} for item in sorted(families)],
    }
