"""Exact Online OAuth token refresh via the connections table."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from r2r import supabase_rest
from provider.exact.const import EXACT_CLIENT_ID, EXACT_CLIENT_SECRET, EXACT_TOKEN_URL

logger = logging.getLogger(__name__)


def get_organization_connection(organization_id: str) -> dict[str, Any]:
    try:
        row = supabase_rest.select(
            "connections",
            columns="id,organization_id,access_token,refresh_token,expires_at,division",
            filters={"organization_id": organization_id},
            maybe_single=True,
        )
    except supabase_rest.SupabaseRestError as exc:
        return {"connected": False, "error": str(exc)}

    if not row:
        return {
            "connected": False,
            "error": f"No connection found for organization {organization_id}",
        }
    return _process_connection_token(row)


def _process_connection_token(connection: dict[str, Any]) -> dict[str, Any]:
    expires_at = connection.get("expires_at")
    try:
        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return {"connected": False, "error": "Invalid expires_at in connection"}

    now = datetime.now(timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires > now:
        return {
            "connected": True,
            "access_token": connection.get("access_token"),
            "division": connection.get("division"),
        }

    refresh_token = connection.get("refresh_token")
    if not refresh_token:
        try:
            supabase_rest.delete("connections", filters={"id": str(connection["id"])})
        except Exception:
            logger.warning("Failed to delete connection without refresh token")
        return {
            "connected": False,
            "error": "No refresh token available. Please reconnect your Exact Online account.",
        }

    if not EXACT_CLIENT_ID or not EXACT_CLIENT_SECRET:
        return {"connected": False, "error": "EXACT_CLIENT_ID / EXACT_CLIENT_SECRET not configured"}

    last_error = "token refresh failed"
    for attempt in range(1, 4):
        response = requests.post(
            EXACT_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": EXACT_CLIENT_ID,
                "client_secret": EXACT_CLIENT_SECRET,
            },
            timeout=30,
        )
        if response.ok:
            token_data = response.json()
            access_token = token_data["access_token"]
            new_refresh = token_data.get("refresh_token") or refresh_token
            expires_in = int(token_data.get("expires_in") or 600)
            new_expires = datetime.now(timezone.utc).timestamp() + expires_in
            new_expires_iso = datetime.fromtimestamp(new_expires, tz=timezone.utc).isoformat()
            supabase_rest.update(
                "connections",
                {
                    "access_token": access_token,
                    "refresh_token": new_refresh,
                    "expires_at": new_expires_iso,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                filters={"id": str(connection["id"])},
            )
            return {
                "connected": True,
                "access_token": access_token,
                "division": connection.get("division"),
            }

        last_error = response.text
        if "Old refresh token used" in last_error or "unauthorized_client" in last_error:
            return {
                "connected": False,
                "error": f"Refresh token expired or invalid. Re-authentication required: {last_error}",
            }
        if "invalid_grant" in last_error and attempt < 3:
            time.sleep(attempt)
            continue
        break

    return {"connected": False, "error": last_error}


def require_connection(organization_id: str) -> tuple[str, int]:
    token = get_organization_connection(organization_id)
    if not token.get("connected") or not token.get("access_token") or token.get("division") is None:
        raise RuntimeError(token.get("error") or "Exact Online is not connected for this organization")
    return str(token["access_token"]), int(token["division"])
