"""快照匯出的命令列入口。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from serving.snapshot import fetch_snapshot, write_gcs, write_local


def main() -> None:
    parser = argparse.ArgumentParser(description="產生路線建議網頁用的資料快照")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", type=Path, help="寫到本機檔案")
    target.add_argument("--gcs", help="上傳到 GCS，例如 gs://bucket/snapshot.json")
    args = parser.parse_args()

    load_dotenv(".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

    snapshot = fetch_snapshot()
    if args.out:
        write_local(snapshot, args.out)
        print(f"已寫入 {args.out}（{len(snapshot['stations'])} 個站點）")
    else:
        write_gcs(snapshot, args.gcs)


if __name__ == "__main__":
    main()
