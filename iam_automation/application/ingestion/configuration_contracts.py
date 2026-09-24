"""Typed draft contracts for the ingestion template configuration laboratory.

These contracts describe a draft configuration only. Versioned snapshots may be
saved for review, but this is not the runtime ``SourceDefinition`` contract and
must not be used by the production ingestion lifecycle yet.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DRAFT_FORMATS: tuple[str, ...] = ("CSV", "XLSX")
DRAFT_FIELD_TYPES: tuple[str, ...] = (
    "string",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "enum",
)
DRAFT_TRANSFORMS: tuple[str, ...] = (
    "identity",
    "trim",
    "lower",
    "upper",
    "parse_date",
    "normalize_email",
    "normalize_id",
)
DRAFT_TRANSFORM_LABELS: dict[str, str] = {
    "identity": "Keep as provided",
    "trim": "Remove extra spaces",
    "lower": "Convert to lowercase",
    "upper": "Convert to uppercase",
    "parse_date": "Clean date text",
    "normalize_email": "Normalize email",
    "normalize_id": "Normalize identifier",
}
DRAFT_TRANSFORM_DESCRIPTIONS: dict[str, str] = {
    "identity": "Leaves the source value unchanged.",
    "trim": "Removes spaces before and after the value.",
    "lower": "Converts letters to lowercase.",
    "upper": "Converts letters to uppercase.",
    "parse_date": "Removes extra spaces before date validation.",
    "normalize_email": "Trims the address and converts it to lowercase.",
    "normalize_id": "Trims the identifier and preserves leading zeroes.",
}
DRAFT_VALIDATION_KINDS: tuple[str, ...] = (
    "required",
    "nullable",
    "identifier",
    "enum",
    "date_format",
    "min_length",
    "max_length",
    "regex",
    "duplicate_source_key",
)
DRAFT_DRIFT_POLICIES: tuple[str, ...] = ("INFO", "WARNING", "BLOCKING")
DRAFT_IDENTITY_ROLES: tuple[str, ...] = (
    "IDENTITY_SEED",
    "IDENTITY_ENRICHMENT",
    "EVIDENCE_ONLY",
)
DRAFT_IDENTITY_ROLE_LABELS: dict[str, str] = {
    "IDENTITY_SEED": "Identity Seed",
    "IDENTITY_ENRICHMENT": "Identity Enrichment",
    "EVIDENCE_ONLY": "Evidence Only",
}
DRAFT_IDENTITY_ROLE_DESCRIPTIONS: dict[str, str] = {
    "IDENTITY_SEED": "Needs at least two Strong identifiers authorized for matching and creation before it can propose a new Employee UUID.",
    "IDENTITY_ENRICHMENT": "Needs at least one Strong identifier to find existing employees; cannot create a new Employee UUID.",
    "EVIDENCE_ONLY": "Keeps source evidence available without authorizing identity matching or creation.",
}
DRAFT_IDENTITY_STRENGTHS: tuple[str, ...] = ("STRONG", "SUPPORTING")
# Existing and new templates start with this configurable per-template value.
DEFAULT_IDENTITY_MATCHING_LIMIT = 3


@dataclass(frozen=True)
class DraftReaderSettings:
    format: str = "XLSX"
    watched_path: str = ""
    filename_pattern: str = ""
    sheet_name: str = ""
    header_row: int = 1
    header_rows: tuple[int, ...] = (1,)
    csv_delimiter: str = ","


@dataclass(frozen=True)
class DraftRecognitionSettings:
    filename_pattern: str = ""
    extension: str = ".xlsx"
    sheet_name: str = ""
    required_headers: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftFieldDefinition:
    source_name: str
    field_key: str
    include: bool = True
    data_type: str = "string"
    inferred_type: str = "string"
    transform_name: str = "identity"
    inferred_transform: str = "identity"
    required: bool = False
    nullable: bool = True
    identifier: bool = False
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftFieldMapping:
    source_field: str
    target_field: str = ""
    transform_name: str = "identity"


@dataclass(frozen=True)
class DraftIdentityIdentifier:
    """A source-schema field's future identity authority, still draft-only."""

    field_key: str
    strength: str = "SUPPORTING"
    can_match: bool = False
    can_create_identity: bool = False


@dataclass(frozen=True)
class DraftIdentityGovernance:
    """Identity authority declared by a draft template, not executed here."""

    role: str = "EVIDENCE_ONLY"
    can_create_employee: bool = False
    identifiers: tuple[DraftIdentityIdentifier, ...] = ()
    max_matching_fields: int = DEFAULT_IDENTITY_MATCHING_LIMIT


@dataclass(frozen=True)
class DraftDateTimeSettings:
    timezone_mode: str = "RULE_CALENDAR"
    source_timezone: str = ""
    target_timezone: str = ""
    calendar_id: str = ""
    calendar_version_id: str = ""
    calendar_label: str = ""
    field_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftFieldSkipRule:
    field_key: str
    condition: str
    comparison_value: str


@dataclass(frozen=True)
class DraftValidationDefinition:
    kind: str
    field_key: str = ""
    parameter: str = ""


@dataclass(frozen=True)
class DraftSourceDefinition:
    source_id: str = ""
    display_name: str = ""
    description: str = ""
    reader_settings: DraftReaderSettings = field(default_factory=DraftReaderSettings)
    recognition_settings: DraftRecognitionSettings = field(default_factory=DraftRecognitionSettings)
    fields: tuple[DraftFieldDefinition, ...] = ()
    identity_governance: DraftIdentityGovernance = field(default_factory=DraftIdentityGovernance)
    watched_subfolder: str = ""
    date_time_settings: DraftDateTimeSettings = field(default_factory=DraftDateTimeSettings)
    skip_rules: tuple[DraftFieldSkipRule, ...] = ()
    mappings: tuple[DraftFieldMapping, ...] = ()
    validations: tuple[DraftValidationDefinition, ...] = ()
    schema_drift_policy: str = "WARNING"
    status: str = "DRAFT"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/session-safe representation of this draft."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "DraftSourceDefinition":
        """Rehydrate a draft while tolerating an empty or older session value."""
        payload = payload if isinstance(payload, dict) else {}
        reader = payload.get("reader_settings") or {}
        recognition = payload.get("recognition_settings") or {}
        fields = tuple(
            DraftFieldDefinition(
                source_name=str(item.get("source_name", "")),
                field_key=str(item.get("field_key", "")),
                include=bool(item.get("include", True)),
                data_type=str(item.get("data_type", "string")),
                inferred_type=str(item.get("inferred_type", item.get("data_type", "string"))),
                transform_name=str(item.get("transform_name", "identity")),
                inferred_transform=str(item.get("inferred_transform", item.get("transform_name", "identity"))),
                required=bool(item.get("required", False)),
                nullable=bool(item.get("nullable", True)),
                identifier=bool(item.get("identifier", False)),
                enum_values=tuple(str(value) for value in item.get("enum_values", ()) or ()),
            )
            for item in payload.get("fields", ()) or ()
            if isinstance(item, dict)
        )
        mappings = tuple(
            DraftFieldMapping(
                source_field=str(item.get("source_field", "")),
                target_field=str(item.get("target_field", "")),
                transform_name=str(item.get("transform_name", "identity")),
            )
            for item in payload.get("mappings", ()) or ()
            if isinstance(item, dict)
        )
        identity_payload = payload.get("identity_governance") or {}
        try:
            max_matching_fields = int(identity_payload.get("max_matching_fields", DEFAULT_IDENTITY_MATCHING_LIMIT))
        except (TypeError, ValueError):
            max_matching_fields = DEFAULT_IDENTITY_MATCHING_LIMIT
        if max_matching_fields < 1:
            max_matching_fields = DEFAULT_IDENTITY_MATCHING_LIMIT
        identity_identifiers = tuple(
            DraftIdentityIdentifier(
                field_key=str(item.get("field_key", "")),
                strength=str(item.get("strength", "SUPPORTING")).upper(),
                can_match=bool(item.get("can_match", False)),
                can_create_identity=bool(item.get("can_create_identity", False)),
            )
            for item in identity_payload.get("identifiers", ()) or ()
            if isinstance(item, dict) and str(item.get("field_key", "")).strip()
        )
        validations = tuple(
            DraftValidationDefinition(
                kind=str(item.get("kind", "")),
                field_key=str(item.get("field_key", "")),
                parameter=str(item.get("parameter", "")),
            )
            for item in payload.get("validations", ()) or ()
            if isinstance(item, dict)
        )
        date_time_payload = payload.get("date_time_settings") or {}
        skip_rules = tuple(
            DraftFieldSkipRule(
                field_key=str(item.get("field_key", "")),
                condition=str(item.get("condition", "")).upper(),
                comparison_value=str(item.get("comparison_value", "")),
            )
            for item in payload.get("skip_rules", ()) or ()
            if isinstance(item, dict)
            and str(item.get("field_key", "")).strip()
            and str(item.get("condition", "")).upper() in {"BEFORE", "AFTER", "ON_OR_BEFORE", "ON_OR_AFTER"}
            and str(item.get("comparison_value", "")).strip()
        )
        return cls(
            source_id=str(payload.get("source_id", "")),
            display_name=str(payload.get("display_name", "")),
            description=str(payload.get("description", "")),
            reader_settings=DraftReaderSettings(
                format=str(reader.get("format", "XLSX")),
                watched_path=str(reader.get("watched_path", "")),
                filename_pattern=str(reader.get("filename_pattern", "")),
                sheet_name=str(reader.get("sheet_name", "")),
                header_row=int(reader.get("header_row", 1) or 1),
                header_rows=tuple(int(value) for value in reader.get("header_rows", (reader.get("header_row", 1),)) or (reader.get("header_row", 1),)),
                csv_delimiter=str(reader.get("csv_delimiter", ",")) or ",",
            ),
            recognition_settings=DraftRecognitionSettings(
                filename_pattern=str(recognition.get("filename_pattern", "")),
                extension=str(recognition.get("extension", ".xlsx")),
                sheet_name=str(recognition.get("sheet_name", "")),
                required_headers=tuple(str(value) for value in recognition.get("required_headers", ()) or ()),
            ),
            fields=fields,
            identity_governance=DraftIdentityGovernance(
                role=str(identity_payload.get("role", "EVIDENCE_ONLY")).upper(),
                can_create_employee=bool(identity_payload.get("can_create_employee", False)),
                identifiers=identity_identifiers,
                max_matching_fields=max_matching_fields,
            ),
            watched_subfolder=str(payload.get("watched_subfolder", "")),
            date_time_settings=DraftDateTimeSettings(
                timezone_mode=str(date_time_payload.get("timezone_mode", "RULE_CALENDAR")).upper(),
                source_timezone=str(date_time_payload.get("source_timezone", "")),
                target_timezone=str(date_time_payload.get("target_timezone", "")),
                calendar_id=str(date_time_payload.get("calendar_id", "")),
                calendar_version_id=str(date_time_payload.get("calendar_version_id", "")),
                calendar_label=str(date_time_payload.get("calendar_label", "")),
                field_keys=tuple(str(value) for value in date_time_payload.get("field_keys", ()) or ()),
            ),
            skip_rules=skip_rules,
            mappings=mappings,
            validations=validations,
            schema_drift_policy=str(payload.get("schema_drift_policy", "WARNING")),
            status="DRAFT",
        )
