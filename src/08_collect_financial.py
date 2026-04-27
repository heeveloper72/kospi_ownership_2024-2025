#!/usr/bin/env python3
"""전체 상장사의 재무제표(fnlttSinglAcntAll) 데이터를 수집.

H1(2014 상장 × 지분율) / H5(재벌 × 개혁) 가설의 공통 통제변수용:
자산총계, 부채총계, 자본총계, 매출액, 영업이익.

수집 전략:
  1. 연결재무제표(CFS) 우선 호출.
  2. CFS 데이터 없음(status=013) 또는 오류 → 개별재무제표(OFS) fallback.
  3. 둘 다 없으면 행 생략 + 체크포인트만 기록(재호출 방지).

평균 호출 수: ~29,271건 × 약 1.3배(CFS 미제공사 fallback) ≈ 38,000건 / 4일.
"""

import logging
import os
import time
from typing import Any

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

CHECKPOINT_PATH = DATA_RAW / "financial_checkpoint.json"
OUTPUT_PATH = DATA_RAW / "financial_raw.csv"
YEARS = list(range(2015, 2026))

# GitHub Actions 6h timeout 직전에 안전 종료 (finally 블록 정상 실행 보장)
# 5h25m 후 break → upload/auto-trigger 단계가 정상 실행될 25분 여유 확보
MAX_RUNTIME_SEC = int(os.environ.get("STEP8_MAX_RUNTIME_SEC", 5 * 3600 + 25 * 60))

FIELDNAMES = [
    "corp_code", "corp_name", "market", "year", "fs_div_used",
    "total_assets", "total_liabilities", "total_equity",
    "revenue", "operating_income",
]

# account_nm 매칭 규칙 — DART 응답의 한글 표준 계정명 변이 대응
ACCOUNT_MAP: dict[str, list[str]] = {
    "total_assets":      ["자산총계"],
    "total_liabilities": ["부채총계"],
    "total_equity":      ["자본총계"],
    "revenue":           ["매출액", "수익(매출액)", "영업수익", "매출"],
    "operating_income":  ["영업이익", "영업이익(손실)"],
}

# sj_div 필터 (요청 시 응답 축소 목적 아님 — 응답에서 필터링)
SJ_DIV_BS = "BS"   # 재무상태표 (자산·부채·자본)
SJ_DIV_IS = ("IS", "CIS")  # 손익계산서 / 포괄손익계산서 (매출·영업이익)


def extract_metrics(data: dict[str, Any]) -> dict[str, str]:
    """응답의 list에서 타겟 계정을 찾아 thstrm_amount 반환(문자열 원본)."""
    result: dict[str, str] = {k: "" for k in ACCOUNT_MAP}
    items = data.get("list", [])

    for target_col, name_candidates in ACCOUNT_MAP.items():
        expected_sj = (SJ_DIV_BS,) if target_col in ("total_assets", "total_liabilities", "total_equity") else SJ_DIV_IS
        for item in items:
            if item.get("sj_div") not in expected_sj:
                continue
            account_nm = str(item.get("account_nm", "")).strip()
            if account_nm in name_candidates:
                amount = str(item.get("thstrm_amount", "")).strip()
                if amount and amount != "-":
                    result[target_col] = amount
                    break  # 첫 매칭만 사용 (동명 계정 중복 방지)
    return result


def collect_for_task(
    api_key: str,
    corp_code: str,
    bsns_year: str,
    counter: dict[str, Any],
) -> tuple[dict[str, str] | None, str]:
    """CFS → OFS fallback 로 한 (corp, year) 재무데이터 수집.

    Returns:
        (metrics_dict or None, fs_div_used)
        fs_div_used: "CFS" | "OFS" | "NONE"
    """
    for fs_div in ("CFS", "OFS"):
        if is_daily_limit_reached(counter):
            return None, "LIMIT"

        data = call_dart_api("fnlttSinglAcntAll", api_key, {
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": "11011",
            "fs_div": fs_div,
        })
        counter["calls"] += 1
        time.sleep(SLEEP_SEC)

        if data and data.get("list"):
            metrics = extract_metrics(data)
            if any(v for v in metrics.values()):
                return metrics, fs_div

    return None, "NONE"


def collect_financial() -> None:
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
    start_time = time.time()
    try:
        for corp_code, corp_name, market, year in remaining:
            elapsed = time.time() - start_time
            if elapsed > MAX_RUNTIME_SEC:
                logger.warning(
                    f"실행 시간 한도 도달 ({elapsed/3600:.1f}h > {MAX_RUNTIME_SEC/3600:.1f}h) "
                    f"— 안전 종료. 내일 재실행하면 이어서 진행됩니다."
                )
                break

            if is_daily_limit_reached(counter):
                logger.warning(
                    f"일일 한도 도달 — 잔여 {total - done}건. "
                    "내일 재실행하면 이어서 진행됩니다."
                )
                break

            metrics, fs_div_used = collect_for_task(api_key, corp_code, year, counter)
            processed_this_run += 1

            if fs_div_used == "LIMIT":
                break

            if metrics:
                append_to_csv(OUTPUT_PATH, [{
                    "corp_code": corp_code,
                    "corp_name": corp_name,
                    "market": market,
                    "year": year,
                    "fs_div_used": fs_div_used,
                    **metrics,
                }], FIELDNAMES)

            # 무자료여도 체크포인트 저장 — 재호출 방지
            mark_completed(checkpoint, corp_code, year)
            done += 1

            if processed_this_run % 100 == 0:
                save_checkpoint(CHECKPOINT_PATH, checkpoint)
                save_daily_counter(counter)
                logger.info(
                    f"진행: {done}/{total} ({done / total * 100:.1f}%) "
                    f"| 오늘 호출: {counter['calls']}"
                )

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
    collect_financial()


if __name__ == "__main__":
    main()
