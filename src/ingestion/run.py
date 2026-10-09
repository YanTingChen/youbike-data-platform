"""擷取流程的命令列入口。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from ingestion.config import Settings
from ingestion.pipeline import DATASETS, extract_to_gcs, extract_to_local, load_to_bigquery
from ingestion.transform import utc_now


def main() -> None:
    parser = argparse.ArgumentParser(description="台中 YouBike 2.0 資料擷取")
    parser.add_argument("dataset", choices=sorted(DATASETS))
    parser.add_argument("--local", action="store_true", help="只寫到本機 ./data，不上傳 GCP")
    parser.add_argument("--out-dir", default="data", help="--local 時的輸出資料夾")
    args = parser.parse_args()

    load_dotenv()  # 讀取專案根目錄的 .env

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    ingested_at = utc_now()

    if args.local:
        settings = Settings.from_env(require_gcp=False)
        path = extract_to_local(args.dataset, settings, ingested_at, Path(args.out_dir))
        print(f"\n已寫入 {path}")
        return

    settings = Settings.from_env()
    result = extract_to_gcs(args.dataset, settings, ingested_at)
    rows = load_to_bigquery(args.dataset, settings, result["staged_uri"])
    print(f"完成：{result['staged_uri']} → BigQuery {rows} 列")


if __name__ == "__main__":
    main()
