#!/usr/bin/env python3
"""KRX 연말 시가총액 수집 (H3 Tobin's Q 분모 시계열).

pykrx로 연도별 전체 상장 종목의 연말 종가 기준 시가총액을 수집.
DART API와 별도 경로이므로 DART 일일 한도와 무관.

연도별 1회 호출(전체 종목 일괄 수신) → 2015~2025 총 11회 API 호출.
"""

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from utils import DATA_RAW, append_to_csv, load_checkpoint, mark_completed, save_checkpoint

try:
    from pykrx import stock as pykrx_stock
except ImportError as e:
    raise ImportError("pykrx 미설치 — requirements.txt 확인") from e

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CHECKPOINT_PATH = DATA_RAW / "market_cap_checkpoint.json"
OUTPUT_PATH = DATA_RAW / "market_cap_raw.csv"
YEARS = list(range(2015, 2026))
FIELDNAMES = [
    "corp_code", "corp_name", "stock_code", "market",
    "year", "snapshot_date", "market_cap", "shares",
]
YEAREND_SLEEP_SEC = 1.0  # KRX 서버 예의


def find_last_trading_day(year: int) -> str:
    """해당 연도의 마지막 거래일을 YYYYMMDD로 반환.

    12/31부터 거꾸로 최대 10일 시도. pykrx 응답이 비어있으면 휴장으로 판단.
    현재 연도이고 아직 연말 전이면 '오늘' 또는 가장 최근 거래일 반환.
    """
    today = date.today()
    candidate = date(year, 12, 31)
    if candidate > today:
        candidate = today

    for _ in range(15):
        dt_str = candidate.strftime("%Y%m%d")
        df = pykrx_stock.get_market_ohlcv_by_ticker(dt_str, market="ALL")
        if df is not None and not df.empty:
            return dt_str
        candidate -= timedelta(days=1)
        time.sleep(0.3)

    raise RuntimeError(f"{year}년 거래일을 찾지 못함")


def collect_year(year: int, corps: pd.DataFrame) -> int:
    """해당 연도 연말 시가총액을 전체 상장사에 대해 수집. 저장 행수 반환."""
    snapshot_date = find_last_trading_day(year)
    logger.info(f"[{year}] 스냅샷 거래일: {snapshot_date}")

    df_cap = pykrx_stock.get_market_cap_by_ticker(snapshot_date, market="ALL")
    if df_cap is None or df_cap.empty:
        logger.warning(f"[{year}] pykrx 응답 비어있음 — 스킵")
        return 0

    # pykrx 컬럼: 시가총액, 거래량, 거래대금, 상장주식수
    df_cap = df_cap.reset_index().rename(columns={"티커": "stock_code"})
    df_cap["stock_code"] = df_cap["stock_code"].astype(str).str.zfill(6)

    merged = corps.merge(df_cap, on="stock_code", how="inner")
    logger.info(
        f"[{year}] KRX {len(df_cap)}종목 ↔ 상장사 매칭 {len(merged)}/{len(corps)}"
    )

    rows = [
        {
            "corp_code": r["corp_code"],
            "corp_name": r["corp_name"],
            "stock_code": r["stock_code"],
            "market": r["market"],
            "year": str(year),
            "snapshot_date": snapshot_date,
            "market_cap": int(r["시가총액"]) if pd.notna(r["시가총액"]) else "",
            "shares": int(r["상장주식수"]) if pd.notna(r["상장주식수"]) else "",
        }
        for _, r in merged.iterrows()
    ]
    if rows:
        append_to_csv(OUTPUT_PATH, rows, FIELDNAMES)
    return len(rows)


def main() -> None:
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    corps_path = DATA_RAW / "listed_corps.csv"
    if not corps_path.exists():
        raise FileNotFoundError("listed_corps.csv가 없습니다. 먼저 01_get_corp_list.py를 실행하세요.")

    corps = pd.read_csv(corps_path, dtype=str)
    corps["stock_code"] = corps["stock_code"].astype(str).str.strip().str.zfill(6)
    logger.info(f"상장사 {len(corps)}개 로드")

    checkpoint = load_checkpoint(CHECKPOINT_PATH)
    completed_years = set(checkpoint.get("completed", {}).get("_ALL", []))
    remaining = [y for y in YEARS if str(y) not in completed_years]
    logger.info(f"대상 연도 {len(YEARS)}년 중 완료 {len(YEARS) - len(remaining)}년, 잔여 {len(remaining)}년")

    try:
        for year in remaining:
            t0 = datetime.now()
            n_rows = collect_year(year, corps)
            elapsed = (datetime.now() - t0).total_seconds()
            logger.info(f"[{year}] 저장 {n_rows}행 | 소요 {elapsed:.1f}초")

            mark_completed(checkpoint, "_ALL", str(year))
            save_checkpoint(CHECKPOINT_PATH, checkpoint)
            time.sleep(YEAREND_SLEEP_SEC)
    finally:
        save_checkpoint(CHECKPOINT_PATH, checkpoint)
        done = len(checkpoint.get("completed", {}).get("_ALL", []))
        logger.info(f"체크포인트 저장. 완료 연도: {done}/{len(YEARS)}")


if __name__ == "__main__":
    main()
