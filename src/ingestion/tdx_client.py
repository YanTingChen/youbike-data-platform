"""TDX 運輸資料流通服務 API 客戶端。

- 以 OAuth2 client_credentials 取得 access token，並快取到過期前 1 分鐘
- 所有請求都有 timeout，遇到 429／5xx 自動指數退避重試
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
API_BASE = "https://tdx.transportdata.tw/api/basic"


class TDXClient:
    def __init__(self, client_id: str, client_secret: str, timeout: float = 30.0) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at = 0.0

        retry = Retry(
            total=3,
            backoff_factor=2,  # 2、4、8 秒
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        resp = self._session.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + float(body.get("expires_in", 86400))
        return self._token

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        headers = {
            "authorization": f"Bearer {self._get_token()}",
            "Accept-Encoding": "gzip",
        }
        query = {"$format": "JSON", **(params or {})}
        started = time.monotonic()
        resp = self._session.get(f"{API_BASE}{path}", headers=headers, params=query, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "TDX GET %s 完成：%d 筆，耗時 %.2f 秒",
            path,
            len(data) if isinstance(data, list) else 1,
            time.monotonic() - started,
        )
        return data

    def get_bike_availability(self, city: str) -> list[dict[str, Any]]:
        """即時車況：可借車數、可還空位、服務狀態。"""
        return self.get(f"/v2/Bike/Availability/City/{city}")

    def get_bike_stations(self, city: str) -> list[dict[str, Any]]:
        """站點基本資料：站名、座標、地址、總車位數。"""
        return self.get(f"/v2/Bike/Station/City/{city}")
