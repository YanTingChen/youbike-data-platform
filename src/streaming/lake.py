"""從資料湖（GCS）讀取批次擷取剛存下的檔案。

串流不另外呼叫 TDX：TDX 免費額度有限，整個平台只由批次擷取呼叫 API，
串流讀取同一份資料，API 用量只取決於批次擷取的頻率。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from ingestion.pipeline import build_object_paths


def staged_prefixes(dataset: str, city: str, now: datetime) -> list[str]:
    """今天與昨天的清洗後檔案所在的目錄。跨日時最新的檔案可能還在前一天的目錄。"""
    prefixes = []
    for moment in (now, now - timedelta(days=1)):
        staged_path = build_object_paths(dataset, city, moment)[1]
        prefixes.append(staged_path.split("/hour=")[0] + "/")
    return prefixes


def newest(names: Iterable[str]) -> str | None:
    """檔名是 UTC 時間戳，依檔名排序即為時間順序。"""
    return max(names, key=lambda name: name.rsplit("/", 1)[-1], default=None)


def latest_staged(client, bucket: str, dataset: str, city: str, now: datetime):
    """回傳最新一份清洗後檔案的 Blob；還沒有任何檔案時回傳 None。"""
    blobs = {
        blob.name: blob
        for prefix in staged_prefixes(dataset, city, now)
        for blob in client.list_blobs(bucket, prefix=prefix)
        if blob.name.endswith(".ndjson")
    }
    name = newest(blobs)
    return blobs[name] if name else None
