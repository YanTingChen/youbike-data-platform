"""模型訓練與推論的命令列入口。"""

from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

from ml.config import MLSettings
from ml.pipeline import NotReadyError, predict, train


def main() -> None:
    parser = argparse.ArgumentParser(description="YouBike 可借車數預測")
    parser.add_argument("command", choices=["train", "predict"])
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    settings = MLSettings.from_env()

    try:
        if args.command == "train":
            print(train(settings))
        else:
            print(f"新增 {predict(settings)} 筆預測")
    except NotReadyError as exc:
        print(f"略過：{exc}")


if __name__ == "__main__":
    main()
