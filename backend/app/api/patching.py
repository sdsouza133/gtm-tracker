"""Applying a PATCH body to a row."""

from typing import Any

from app.models import Base


def apply(row: Base, fields: dict[str, Any]) -> None:
    """Set each field. A null for a column that can't be empty is ignored rather than failing the whole change."""
    columns = row.__table__.columns
    for key, value in fields.items():
        if value is None and key in columns and not columns[key].nullable:
            continue
        setattr(row, key, value)
