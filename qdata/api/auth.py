from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
import time
from typing import Iterable, Mapping

from qdata.exceptions import QDataValidationError


@dataclass(frozen=True)
class TokenIdentity:
    token_id: int | None
    token_hash: str
    token_name: str
    owner: str | None
    scopes: tuple[str, ...]
    quota_per_min: int
    tenant_id: int | None = None
    project_id: int | None = None
    principal_id: int | None = None
    cost_center: str | None = None


class AuthError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenAuth:
    def __init__(
        self,
        tokens: Iterable[str] | None = None,
        postgres_dsn: str | None = None,
        allow_anonymous: bool | None = None,
        quota_per_min: int = 120,
        token_scopes: Iterable[str] | None = None,
    ) -> None:
        configured = [token for token in (tokens or []) if token]
        scopes = tuple(token_scopes or ("read",))
        self.postgres_dsn = postgres_dsn
        self._identities = {
            hash_token(token): TokenIdentity(
                token_id=None,
                token_hash=hash_token(token),
                token_name="env-token",
                owner="env",
                scopes=scopes,
                quota_per_min=quota_per_min,
                tenant_id=None,
                project_id=None,
                principal_id=None,
                cost_center=None,
            )
            for token in configured
        }
        self.allow_anonymous = allow_anonymous if allow_anonymous is not None else not configured and not postgres_dsn
        self._usage: dict[str, list[float]] = {}

    @classmethod
    def from_env(
        cls,
        postgres_dsn: str | None = None,
        tokens: Iterable[str] | None = None,
        token_scopes: Iterable[str] | None = None,
    ) -> "TokenAuth":
        env_tokens = [item.strip() for item in os.getenv("QDATA_API_TOKENS", "").split(",") if item.strip()]
        env_scopes = [item.strip() for item in os.getenv("QDATA_API_TOKEN_SCOPES", "").split(",") if item.strip()]
        return cls(tokens=list(tokens or []) or env_tokens, postgres_dsn=postgres_dsn, token_scopes=list(token_scopes or []) or env_scopes or ("read",))

    def authenticate(self, headers: Mapping[str, str], required_scope: str = "read") -> TokenIdentity:
        token = _extract_token(headers)
        if not token:
            if self.allow_anonymous:
                identity = TokenIdentity(None, "anonymous", "anonymous", None, ("read",), 60)
                self._authorize_scope(identity, required_scope)
                self._check_quota(identity)
                return identity
            raise AuthError(401, "missing bearer token")

        token_hash = hash_token(token)
        identity = self._identities.get(token_hash)
        if identity is None and self.postgres_dsn:
            identity = self._load_db_identity(token_hash)
        if identity is None:
            raise AuthError(401, "invalid bearer token")
        self._authorize_scope(identity, required_scope)
        self._check_quota(identity)
        return identity

    def _load_db_identity(self, token_hash: str) -> TokenIdentity | None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise QDataValidationError("psycopg is required for database API token validation") from exc
        try:
            with psycopg.connect(self.postgres_dsn, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT token_id, token_hash, token_name, owner, scopes, quota_per_min,
                               tenant_id, project_id, principal_id, cost_center
                        FROM qmeta.api_token
                        WHERE token_hash = %s
                          AND is_active = TRUE
                          AND (expires_at IS NULL OR expires_at > now())
                        """,
                        (token_hash,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    cursor.execute("UPDATE qmeta.api_token SET last_used_at = now() WHERE token_id = %s", (row["token_id"],))
        except Exception:
            return None
        scopes = tuple(row["scopes"] or ())
        return TokenIdentity(
            token_id=row["token_id"],
            token_hash=row["token_hash"],
            token_name=row["token_name"],
            owner=row["owner"],
            scopes=scopes,
            quota_per_min=row["quota_per_min"],
            tenant_id=row.get("tenant_id"),
            project_id=row.get("project_id"),
            principal_id=row.get("principal_id"),
            cost_center=row.get("cost_center"),
        )

    @staticmethod
    def _authorize_scope(identity: TokenIdentity, required_scope: str) -> None:
        if identity.scopes and required_scope not in identity.scopes and "admin" not in identity.scopes:
            raise AuthError(403, f"token lacks required scope: {required_scope}")

    def _check_quota(self, identity: TokenIdentity) -> None:
        now = time.time()
        window_start = now - 60
        usage = [timestamp for timestamp in self._usage.get(identity.token_hash, []) if timestamp >= window_start]
        if len(usage) >= identity.quota_per_min:
            raise AuthError(429, "api token quota exceeded")
        usage.append(now)
        self._usage[identity.token_hash] = usage


def _extract_token(headers: Mapping[str, str]) -> str | None:
    api_token = headers.get("X-API-Token") or headers.get("x-api-token")
    if api_token:
        return api_token.strip()
    authorization = headers.get("Authorization") or headers.get("authorization")
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()
