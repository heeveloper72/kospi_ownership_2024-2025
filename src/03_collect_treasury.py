#!/usr/bin/env python3
"""전체 상장사의 자기주식 취득·처분 현황(tesstkAcqsDspsSttus) 데이터를 수집."""

import logging
import time
from pathlib import Path

import pandas as pd

from utils import (
    DATA_RAW,
    DAILY_LIMIT,
    SLEEP_SEC,
    append_to_csv,
    call_dart_api,
    load_api_key,
    load_checkpoint,
    save_checkpoint,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CHECKPOINT_PATH = DATA_RAW / "treasury_checkpoint.json"
OUTPUT_PATH = DATA_RAW / "treasury_raw.csv"
YEARS = list(range(2015, 2026))
FIELDNAMES = [
    "corp_code", "corp_name", "market", "year",
    "stock_knd", "acqs_mth1", "acqs_mth2", "acqs_mth3",
    "bsis_qy", "change_qy", "trmend_qy", "trmend_rate",
]


def collect_treasury() -> None:
    api_key = load_api_key()

    corps_path = DATA_RAW / "listed_corps.csv"
    if not corps_path.exists():
        raise FileNotFoundError("listed_corps.csv가 없습니다. 먼저 01_get_corp_list.py를 실행하세요.")

    corps = pd.read_csv(corps_path, dtype=str)
    logger.info(f"상장사 {len(corps)}개 로드")

    checkpoint = load_checkpoint(CHECKPOINT_PATH)
    completed_set = set(tuple(x) for x in checkpoint["completed"])
    calls_today = checkpoint["calls_today"]

    all_tasks = [
        (row["corp_code"], row["corp_name"], row["market"], str(year))
        for _, row in corps.iterrows()
        for year in YEARS
    ]
    remaining = [t for t in all_tasks if (t[0], t[3]) not in completed_set]
    total = len(all_tasks)
    done = total - len(remaining)

    logger.info(f"전체 {total}건 중 완료 {done}건, 잔여 {len(remaining)}건")
    logger.info(f"오늘 API 호출: {calls_today}/{DAILY_LIMIT}")

    for corp_code, corp_name, market, year in remaining:
        if calls_today >= DAILY_LIMIT:
            logger.warning(f"일일 한도 {DAILY_LIMIT}건 도달. 자동 중단.")
            break

        data = call_dart_api("tesstkAcqsDspsSttus", api_key, {
            "corp_code": corp_code,
            "bsns_year": year,
            "reprt_code": "11011",
        })
        calls_today += 1

        if data and "list" in data:
            rows = []
            for item in data["list"]:
                rows.append({
                    "corp_code": corp_code,
                    "corp_name": corp_name,
                    "market": market,
                    "year": year,
                    "stock_knd": item.get("stock_knd", ""),
                    "acqs_mth1": item.get("acqs_mth1", ""),
                    "acqs_mth2": item.get("acqs_mth2", ""),
                    "acqs_mth3": item.get("acqs_mth3", ""),
                    "bsis_qy": item.get("bsis_qy", ""),
                    "change_qy": item.get("change_qy", ""),
                    "trmend_qy": item.get("trmend_qy", ""),
                    "trmend_rate": item.get("trmend_rate", ""),
                })
            append_to_csv(OUTPUT_PATH, rows, FIELDNAMES)

        checkpoint["completed"].append([corp_code, year])
        completed_set.add((corp_code, year))
        checkpoint["calls_today"] = calls_today
        done += 1

        if done % 100 == 0:
            save_checkpoint(CHECKPOINT_PATH, checkpoint)
            pct = done / total * 100
            logger.info(f"진행: {done}/{total} ({pct:.1f}%) | 오늘 호출: {calls_today}")

        time.sleep(SLEEP_SEC)

    save_checkpoint(CHECKPOINT_PATH, checkpoint)
    logger.info(f"완료. 총 {done}/{total}건 처리, 오늘 API 호출: {calls_today}")


def main() -> None:
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    collect_treasury()


if __name__ == "__main__":
    main()
