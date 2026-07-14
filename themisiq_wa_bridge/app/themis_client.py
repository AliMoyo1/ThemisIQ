"""ThemisIQ REST API v1 client.

Read-only by design: the API key supplied per tenant is scoped read-only
and the client only issues GETs. Auth uses X-API-Key header (PBKDF2-SHA256,
checked against api_keys table in routes_api_v1.py).

Available endpoints (as of ThemisIQ v1):
  GET /api/v1/risks     filter: status, category
  GET /api/v1/audits    filter: status, audit_type
  GET /api/v1/breaches  filter: status, severity, regulation
"""
from __future__ import annotations

import httpx
from .config import get_settings


class ThemisClient:
    def __init__(self, tenant_id: str, api_key: str):
        self.tenant_id = tenant_id
        self.api_key = api_key
        self.base = get_settings().themis_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def get(self, path: str, **params) -> dict:
        url = self.base + path
        with httpx.Client(timeout=20.0, verify=True) as c:
            r = c.get(url, headers=self._headers(), params=params or None)
            r.raise_for_status()
            return r.json()

    def list_risks(self, status: str = "open", category: str | None = None) -> dict:
        params: dict = {"status": status}
        if category:
            params["category"] = category
        return self.get("/api/v1/risks", **params)

    def list_breaches(self, status: str = "open") -> dict:
        return self.get("/api/v1/breaches", status=status)

    def list_audits(self, status: str | None = None) -> dict:
        params: dict = {}
        if status:
            params["status"] = status
        return self.get("/api/v1/audits", **params)
