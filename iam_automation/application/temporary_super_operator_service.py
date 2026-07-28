from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..identity import ROLE_SUPER_OPERATOR
from ..infrastructure.sqlite.orm import SystemProfileModel, TemporaryElevationModel, orm_session
from .user_service import UserService


class TemporarySuperOperatorService:
    ROLE = ROLE_SUPER_OPERATOR

    def __init__(self, database_path: Path, audit_path: Path | None = None):
        self.database_path = database_path
        self.audit_path = audit_path
        self.users = UserService(database_path)

    def is_enabled(self) -> bool:
        with orm_session(self.database_path) as session:
            profile = session.get(SystemProfileModel, "global_settings")
            if not profile:
                return True
            try:
                return bool(json.loads(profile.profile_json).get("temporary_super_operator_enabled", True))
            except (TypeError, ValueError, json.JSONDecodeError):
                return True

    def effective_roles(self, username: str, base_roles: tuple[str, ...]) -> tuple[str, ...]:
        roles = {str(role).strip().upper() for role in base_roles}
        if self.is_enabled() and self.active_elevation(username):
            roles.add(self.ROLE)
        return tuple(sorted(roles))

    def active_elevation(self, username: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(TemporaryElevationModel).where(TemporaryElevationModel.username == username, TemporaryElevationModel.status == "ACTIVE")).all()
            active = False
            for row in rows:
                if row.expires_at_utc <= now:
                    row.status = "EXPIRED"
                elif row.starts_at_utc <= now:
                    active = True
            return active

    def expire_due(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        expired: list[tuple[str, str]] = []
        with orm_session(self.database_path) as session:
            rows = session.scalars(select(TemporaryElevationModel).where(TemporaryElevationModel.status == "ACTIVE", TemporaryElevationModel.expires_at_utc <= now)).all()
            for row in rows:
                row.status = "EXPIRED"
                expired.append((row.username, row.elevation_id))
        for username, elevation_id in expired:
            self._audit("TEMPORARY_SUPER_OPERATOR_EXPIRED", "system", username, {"elevation_id": elevation_id})
        return len(expired)

    def grant(self, username: str, starts_at_utc: str, expires_at_utc: str, reason: str, granted_by: str) -> str:
        if not reason.strip():
            raise ValueError("A reason is required for temporary elevated access.")
        try:
            # Accept the standard JavaScript UTC suffix as well as Python's
            # explicit offset form, including on Python 3.10.
            starts_at = datetime.fromisoformat(starts_at_utc.replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(expires_at_utc.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Temporary access dates must use ISO 8601 format with a UTC offset.") from exc
        if starts_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("Temporary access dates must include a UTC offset.")
        starts_at_utc = starts_at.astimezone(timezone.utc).isoformat()
        expires_at_utc = expires_at.astimezone(timezone.utc).isoformat()
        if expires_at <= starts_at:
            raise ValueError("Temporary access expiration must be after its start.")
        user = next((item for item in self.users.list_users() if item.username.lower() == username.strip().lower()), None)
        if not user or not user.active or user.status != "ACTIVE":
            raise ValueError("Temporary access requires an active application user.")
        elevation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with orm_session(self.database_path) as session:
            session.add(TemporaryElevationModel(elevation_id=elevation_id, username=user.username, starts_at_utc=starts_at_utc, expires_at_utc=expires_at_utc, reason=reason.strip(), granted_by=granted_by, created_at_utc=now, status="ACTIVE"))
        self._audit("TEMPORARY_SUPER_OPERATOR_GRANTED", granted_by, user.username, {"elevation_id": elevation_id, "starts_at_utc": starts_at_utc, "expires_at_utc": expires_at_utc, "reason": reason.strip()})
        return elevation_id

    def revoke(self, elevation_id: str, actor: str) -> None:
        with orm_session(self.database_path) as session:
            row = session.get(TemporaryElevationModel, elevation_id)
            if row and row.status == "ACTIVE":
                row.status = "REVOKED"
                row.revoked_at_utc = datetime.now(timezone.utc).isoformat()
                username = row.username
            else:
                return
        self._audit("TEMPORARY_SUPER_OPERATOR_REVOKED", actor, username, {"elevation_id": elevation_id})

    def list_all(self):
        self.expire_due()
        with orm_session(self.database_path) as session:
            return session.scalars(select(TemporaryElevationModel).order_by(TemporaryElevationModel.created_at_utc.desc())).all()

    def _audit(self, action: str, actor: str, entity: str, values: dict) -> None:
        if not self.audit_path:
            return
        from .audit_service import record_audit

        record_audit(self.audit_path, actor, action, "temporary_elevation", entity, new_values=values)
