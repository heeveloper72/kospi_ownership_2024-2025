#!/usr/bin/env python3
"""전체 상장사의 최대주주 현황(hyslrSttus) 데이터를 수집."""

import logging
import time

import pandas as pd

from utils import (
    DATA_RAW,
    SLEEP_SEC,
    append_to_csv,
    call_dart_api,
    is_completed,
    is_daily_limit_reached,
    load_api_key,
    load_checkpoint,
    load_daily_counter,
    mark_completed,
    save_checkpoint,
    save_daily_counter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CHECKPOINT_PATH = DATA_RAW / "ownership_checkpoint.json"
OUTPUT_PATH = DATA_RAW / "ownership_raw.csv"
YEARS = list(range(2015, 2026))
FIELDNAMES = [
    "corp_code", "corp_name", "market", "year",
    "nm", "relate", "stock_cnt", "stock_rate",
]


def collect_ownership() -> None:
    api_key = load_api_key()

    corps_path = DATA_RAW / "listed_corps.csv"
    if not corps_path.exists():
        raise FileNotFoundError("listed_corps.csv가 없습니다. 먼저 01_get_corp_list.py를 실행하세요.")

    corps = pd.read_csv(corps_path, dtype=str)
    logger.info(f"상장사 {len(corps)}개 로드")

    checkpoint = load_checkpoint(CHECKPOINT_PATH)
    counter = load_daily_counter()

    all_tasks = [
        (row["corp_code"], row["corp_name"], row["market"], str(year))
        for _, row in corps.iterrows()
        for year in YEARS
    ]
    total = len(all_tasks)
    remaining = [t for t in all_tasks if not is_completed(checkpoint, t[0], t[3])]
    done = total - len(remaining)

    logger.info(f"전체 {total}건 중 완료 {done}건, 잔여 {len(remaining)}건")
    logger.info(f"오늘 API 호출(전체 스크립트 합산): {counter['calls']}/10,000")

    processed_this_run = 0
    try:
        for corp_code, corp_name, market, year in remaining:
            if is_daily_limit_reached(counter):
                logger.warning(
                    f"일일 한도 도달 — 잔여 {total - done}건. "
                    "내일 재실행하면 이어서 진행됩니다."
                )
                break

            data = call_dart_api("hyslrSttus", api_key, {
                "corp_code": corp_code,
                "bsns_year": year,
                "reprt_code": "11011",
            })
            counter["calls"] += 1
            processed_this_run += 1

            if data and "list" in data:
                rows = [
                    {
                        "corp_code": corp_code,
                        "corp_name": corp_name,
                        "market": market,
                        "year": year,
                        "nm": item.get("nm", ""),
                        "relate": item.get("relate", ""),
                        "stock_cnt": item.get("stock_cnt", ""),
                        "stock_rate": item.get("stock_rate", ""),
                    }
                    for item in data["list"]
                ]
                append_to_csv(OUTPUT_PATH, rows, FIELDNAMES)

            mark_completed(checkpoint, corp_code, year)
            done += 1

            if processed_this_run % 100 == 0:
                save_checkpoint(CHECKPOINT_PATH, checkpoint)
                save_daily_counter(counter)
                logger.info(
                    f"진행: {done}/{total} ({done / total * 100:.1f}%) "
                    f"| 오늘 호출: {counter['calls']}"
                )

            time.sleep(SLEEP_SEC)

    finally:
        # Ctrl+C 포함 어떤 중단에도 체크포인트 보존
        save_checkpoint(CHECKPOINT_PATH, checkpoint)
        save_daily_counter(counter)
        logger.info(
            f"체크포인트 저장 완료. "
            f"이번 실행 {processed_this_run}건 처리 | "
            f"전체 진행: {done}/{total} | 오늘 호출: {counter['calls']}"
        )


def main() -> None:
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    collect_ownership()


if __name__ == "__main__":
    main()
