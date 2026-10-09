"""擷取流程的環境設定。"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少環境變數 {name}，請參考 .env.example 設定")
    return value


@dataclass(frozen=True)
class Settings:
    tdx_client_id: str
    tdx_client_secret: str
    city: str
    gcp_project_id: str
    gcs_bucket: str
    bq_raw_dataset: str
    bq_location: str

    @classmethod
    def from_env(cls, require_gcp: bool = True) -> Settings:
        def gcp(name: str, default: str = "") -> str:
            return _require(name) if require_gcp else os.environ.get(name, default)

        return cls(
            tdx_client_id=_require("TDX_CLIENT_ID"),
            tdx_client_secret=_require("TDX_CLIENT_SECRET"),
            city=os.environ.get("TDX_CITY", "Taichung"),
            gcp_project_id=gcp("GCP_PROJECT_ID"),
            gcs_bucket=gcp("GCS_BUCKET"),
            bq_raw_dataset=os.environ.get("BQ_RAW_DATASET", "youbike_raw"),
            bq_location=os.environ.get("BQ_LOCATION", "asia-east1"),
        )
