"""Database-backed source and field catalog for rule configuration."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...infrastructure.sqlite.orm import DimFieldModel, DimSourceModel, SourceFieldMappingModel


class RuleCatalogRepository:
    """Expose governed sources and fields without source-specific constants."""

    def sources(self, session: Any) -> tuple[DimSourceModel, ...]:
        return tuple(session.scalars(
            select(DimSourceModel)
            .where(DimSourceModel.active.is_(True))
            .order_by(DimSourceModel.label.asc(), DimSourceModel.source_system.asc())
        ).all())

    def source_keys(self, session: Any) -> frozenset[str]:
        return frozenset(str(source.source_system).upper() for source in self.sources(session))

    def source_label(self, session: Any, source_system: str) -> str:
        source = session.scalar(select(DimSourceModel).where(
            DimSourceModel.source_system == str(source_system or "").strip().upper(),
            DimSourceModel.active.is_(True),
        ))
        return str(source.label or source.source_system) if source is not None else str(source_system or "")

    def source_id(self, session: Any, source_system: str) -> str | None:
        source = session.scalar(select(DimSourceModel.source_id).where(
            DimSourceModel.source_system == str(source_system or "").strip().upper(),
            DimSourceModel.active.is_(True),
        ))
        return str(source) if source is not None else None

    def source_system(self, session: Any, source_id: str) -> str | None:
        source = session.scalar(select(DimSourceModel.source_system).where(
            DimSourceModel.source_id == str(source_id or ""),
            DimSourceModel.active.is_(True),
        ))
        return str(source) if source is not None else None

    def field_id(self, session: Any, field_key: str) -> str | None:
        field = session.scalar(select(DimFieldModel.field_id).where(
            DimFieldModel.field_key == str(field_key or "").strip(),
            DimFieldModel.active.is_(True),
            DimFieldModel.rule_enabled.is_(True),
        ))
        return str(field) if field is not None else None

    def field_key(self, session: Any, field_id: str) -> str | None:
        field = session.scalar(select(DimFieldModel.field_key).where(
            DimFieldModel.field_id == str(field_id or ""),
            DimFieldModel.active.is_(True),
            DimFieldModel.rule_enabled.is_(True),
        ))
        return str(field) if field is not None else None

    def fields(self, session: Any, source_system: str = "ALL") -> tuple[str, ...]:
        normalized = str(source_system or "ALL").strip().upper()
        query = select(DimFieldModel.field_key).where(
            DimFieldModel.active.is_(True),
            DimFieldModel.rule_enabled.is_(True),
        )
        if normalized != "ALL":
            query = query.join(
                SourceFieldMappingModel,
                SourceFieldMappingModel.field_id == DimFieldModel.field_id,
            ).join(
                DimSourceModel,
                DimSourceModel.source_id == SourceFieldMappingModel.source_id,
            ).where(
                DimSourceModel.source_system == normalized,
                DimSourceModel.active.is_(True),
                SourceFieldMappingModel.active.is_(True),
            )
        return tuple(str(field) for field in session.scalars(query.order_by(DimFieldModel.field_key.asc())).all())

    def condition_fields(self, session: Any) -> tuple[dict[str, str], ...]:
        result: list[dict[str, str]] = []
        for source in self.sources(session):
            for field in self.fields(session, source.source_system):
                result.append({
                    "source": source.source_system,
                    "source_label": source.label or source.source_system,
                    "key": field,
                    "label": field.replace("_", " ").title(),
                })
        return tuple(result)
