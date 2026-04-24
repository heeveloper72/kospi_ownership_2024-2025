#!/usr/bin/env python3
"""DART company.json으로 기업 상세정보(설립일·업종·결산월) 수집.

H1 가설 IV(상장일 전후 2014년 기준 더미) 및 H5 재벌 분류 보조에
필요한 est_dt(설립일), induty_code(업종코드), acc_mt(결산월)를
company.json API로 수집한다.

호출량: ~2,661건 (corp당 1회), 하루 이내 완료.
의존성: DART_API_KEY (.env)
출력: data/raw/corp_details.csv
"""

import logging
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import (
    append_to_csv,
    call_dart_api,
    is_daily_limit_reached,
    load_api_key,
    load_checkpoint,
    load_daily_counter,
    save_checkpoint,
    save_daily_counter,
    SLEEP_SEC,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"

CHECKPOINT_PATH = DATA_RAW / "corp_details_checkpoint.json"
OUTPUT_PATH = DATA_RAW / "corp_details.csv"

FIELDNAMES = [
    "corp_code",
    "corp_name",
    "stock_code",
    "market",
    "est_dt",
    "induty_code",
    "acc_mt",
]

# _ALL 키로 완료된 corp_code 목록 관리 (연도 차원 없음)
COMPLETED_KEY = "_ALL"


def fetch_corp_detail(corp_code: str, api_key: str) -> dict | None:
    """DART company.json API 호출."""
    return call_dart_api("company", api_key, {"corp_code": corp_code})


def main() -> None:
    api_key = load_api_key()

    listed_path = DATA_RAW / "listed_corps.csv"
    if not listed_path.exists():
        raise FileNotFoundError("listed_corps.csv 없음. Step 1을 먼저 실행하세요.")

    df_corps = pd.read_csv(listed_path, dtype=str)
    logger.info(f"상장사 {len(df_corps):,}개 로드")

    cp = load_checkpoint(CHECKPOINT_PATH)
    completed: set[str] = set(cp.get("completed", {}).get(COMPLETED_KEY, []))
    counter = load_daily_counter()

    remaining = [
        row for _, row in df_corps.iterrows()
        if row["corp_code"] not in completed
    ]
    logger.info(f"미수집: {len(remaining):,}건 (완료: {len(completed):,}건)")

    if not remaining:
        logger.info("✅ 이미 전체 수집 완료")
        return

    new_rows: list[dict] = []
    flush_interval = 100

    for idx, row in enumerate(remaining, 1):
        corp_code = str(row["corp_code"])

        if is_daily_limit_reached(counter):
            logger.info(f"일일 한도 도달 ({counter['calls']:,}/10,000) — 오늘 수집 종료")
            break

        data = fetch_corp_detail(corp_code, api_key)
        counter["calls"] += 1
        save_daily_counter(counter)

        if data:
            new_rows.append({
                "corp_code": corp_code,
                "corp_name": row.get("corp_name", ""),
                "stock_code": row.get("stock_code", ""),
                "market": row.get("market", ""),
                "est_dt": data.get("est_dt", ""),
                "induty_code": data.get("induty_code", ""),
                "acc_mt": data.get("acc_mt", ""),
            })

        completed.add(corp_code)
        cp["completed"] = {COMPLETED_KEY: list(completed)}

        if idx % flush_interval == 0:
            append_to_csv(OUTPUT_PATH, new_rows, FIELDNAMES)
            save_checkpoint(CHECKPOINT_PATH, cp)
            logger.info(
                f"  진행 {len(completed):,}/{len(df_corps):,} "
                f"| API {counter['calls']:,}/10,000"
            )
            new_rows = []

        time.sleep(SLEEP_SEC)

    if new_rows:
        append_to_csv(OUTPUT_PATH, new_rows, FIELDNAMES)
    save_checkpoint(CHECKPOINT_PATH, cp)

    total = len(df_corps)
    done = len(completed)
    logger.info(f"수집 완료: {done:,}/{total:,} | API 호출: {counter['calls']:,}/10,000")

    if done >= total:
        logger.info("✅ 전체 수집 완료")
    else:
        logger.info(f"⏳ 잔여 {total - done:,}건 — 내일 재개")


if __name__ == "__main__":
    main()
