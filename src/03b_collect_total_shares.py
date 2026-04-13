#!/usr/bin/env python3
"""전체 상장사의 총발행주식수(stockTotqySttus) 수집.

자사주 비율 계산에 사용:
  treasury_pct = 자사주_기말수량(trmend_qy) / 총발행주식수 * 100
"""

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

CHECKPOINT_PATH = DATA_RAW / "total_shares_checkpoint.json"
OUTPUT_PATH = DATA_RAW / "total_shares_raw.csv"
YEARS = list(range(2015, 2026))

# stockTotqySttus 공식 응답 필드 (DART OpenAPI DS002/2020002).
# 실제 필드명이 카나리아 검증에서 확인되기 전까지 여러 후보를 모두 저장.
# - isu_stock_totqy:          발행할 주식의 총수 (정관상 한도)
# - now_to_isu_stock_totqy:   현재까지 발행한 주식의 총수 (발행누적)
# - redc_stock_totqy:         감소한 주식의 총수 (감자·소각)
# - now_to_redc_stock_totqy:  현재까지 감소한 주식의 총수
# - istc_totqy:               유통주식총수 (현재 발행주식 = 발행누적 − 감소누적)
FIELDNAMES = [
    "corp_code", "corp_name", "market", "year",
    "se",
    "isu_stock_totqy",
    "now_to_isu_stock_totqy",
    "redc_stock_totqy",
    "now_to_redc_stock_totqy",
    "istc_totqy",
]


def collect_total_shares() -> None:
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

            data = call_dart_api("stockTotqySttus", api_key, {
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
                        "se": item.get("se", ""),
                        "isu_stock_totqy":         item.get("isu_stock_totqy", ""),
                        "now_to_isu_stock_totqy":  item.get("now_to_isu_stock_totqy", ""),
                        "redc_stock_totqy":        item.get("redc_stock_totqy", ""),
                        "now_to_redc_stock_totqy": item.get("now_to_redc_stock_totqy", ""),
                        "istc_totqy":              item.get("istc_totqy", ""),
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
        save_checkpoint(CHECKPOINT_PATH, checkpoint)
        save_daily_counter(counter)
        logger.info(
            f"체크포인트 저장 완료. "
            f"이번 실행 {processed_this_run}건 처리 | "
            f"전체 진행: {done}/{total} | 오늘 호출: {counter['calls']}"
        )


def main() -> None:
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    collect_total_shares()


if __name__ == "__main__":
    main()
