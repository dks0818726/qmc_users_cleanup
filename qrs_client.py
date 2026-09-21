"""Minimal, standalone Qlik Repository Service (QRS) client.

Independent of the `qlik_lineage` repo — no shared imports/config. Uses the
same `/custom` virtual-proxy + header-authentication pattern
(`X-Qlik-Xrfkey` + `X-Qlik-User`) that this organization's Qlik environment
requires. No NTLM, no direct QRS port 4242, no client certificates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)


@dataclass
class QrsClient:
    base_url: str
    qlik_user: str
    xrf_key: str
    verify_ssl: bool | str = False
    timeout_seconds: int = 30
    _session: requests.Session = field(default=None, init=False, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._session = requests.Session()
        self._session.verify = self.verify_ssl

    # -- reads ------------------------------------------------------------
    def fetch_users(self, filter_expr: str | None = None) -> list[dict[str, Any]]:
        """GET /qrs/user/full — full user list including custom properties."""
        return self._get("/qrs/user/full", filter_expr=filter_expr)

    # -- writes -------------------------------------------------------------
    def delete_user(self, user_id: str) -> None:
        """DELETE /qrs/user/{id}. Raises on non-2xx response."""
        url = f"{self.base_url.rstrip('/')}/qrs/user/{user_id}"
        params = {"xrfkey": self.xrf_key}
        response = self._session.delete(
            url, params=params, headers=self._headers(), timeout=self.timeout_seconds
        )
        response.raise_for_status()

    # -- HTTP ---------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {
            "X-Qlik-Xrfkey": self.xrf_key,
            "Content-Type": "application/json",
        }
        if self.qlik_user:
            headers["X-Qlik-User"] = self.qlik_user
        return headers

    def _get(self, path: str, filter_expr: str | None = None) -> list[dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}{path}"
        params: dict[str, Any] = {"xrfkey": self.xrf_key}
        if filter_expr:
            params["filter"] = filter_expr
        response = self._session.get(
            url, params=params, headers=self._headers(), timeout=self.timeout_seconds
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        raise ValueError(f"Unexpected QRS payload type: {type(payload)}")
