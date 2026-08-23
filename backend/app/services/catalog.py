from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EquipmentFamily, EquipmentModel, Manufacturer, ManufacturerAlias


def get_catalog_options(db: Session, include_inactive: bool = False) -> dict[str, list[dict[str, object]]]:
    manufacturer_stmt = select(Manufacturer).order_by(Manufacturer.normalized_name)
    family_stmt = select(EquipmentFamily).order_by(EquipmentFamily.normalized_name)
    model_stmt = select(EquipmentModel).order_by(EquipmentModel.normalized_model_name)
    if not include_inactive:
        manufacturer_stmt = manufacturer_stmt.where(Manufacturer.is_active.is_(True))
        family_stmt = family_stmt.where(EquipmentFamily.is_active.is_(True))
        model_stmt = model_stmt.where(EquipmentModel.is_active.is_(True))

    manufacturers = db.scalars(manufacturer_stmt).all()
    aliases = db.scalars(select(ManufacturerAlias)).all()
    alias_map: dict[int, list[str]] = {}
    for alias in aliases:
        alias_map.setdefault(alias.manufacturer_id, []).append(alias.alias)

    families = db.scalars(family_stmt).all()
    models = db.scalars(model_stmt).all()
    return {
        "manufacturers": [
            {
                "id": item.id,
                "value": str(item.id),
                "label": item.name,
                "aliases": sorted(set(alias_map.get(item.id, []))),
                "active": item.is_active,
            }
            for item in manufacturers
        ],
        "equipment_families": [
            {
                "id": item.id,
                "value": str(item.id),
                "label": item.name,
                "manufacturer_id": item.manufacturer_id,
                "active": item.is_active,
            }
            for item in families
        ],
        "equipment_models": [
            {
                "id": item.id,
                "value": str(item.id),
                "label": item.model_name,
                "manufacturer_id": item.manufacturer_id,
                "family_id": item.family_id,
                "active": item.is_active,
            }
            for item in models
        ],
    }
