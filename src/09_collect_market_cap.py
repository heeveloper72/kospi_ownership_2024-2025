#!/usr/bin/env python3
"""KRX 연말 시가총액 수집 (H3 Tobin's Q 분모 시계열).

KRX OpenAPI(openapi.krx.co.kr)로 연도별 전체 상장 종목의
연말 종가 기준 시가총액·상장주식수를 수집.
DART API와 완전히 별도 경로이므로 DART 일일 한도(10,000건)와 무관.

연도별 KOSPI + KOSDAQ 2회 호출 × 11년 = 총 22회 + 거래일 탐색 호출.

사전 요건:
  KRX_AUTH_KEY — openapi.krx.co.kr 에서 발급받은 인증키
    로컬: .env 에 KRX_AUTH_KEY=... 추가
    CI  : GitHub Secrets → KRX_AUTH_KEY, step9-market-cap.yml env 주입

API 인증키 발급:
  1. https://openapi.krx.co.kr 회원가입 (무료)
  2. 마이페이지 > API 인증키 신청 → 이메일 승인 (1영업일 이내)
  3. 서비스 목록에서 "주식 - KOSPI/KOSDAQ 일별 시세" 이용신청

일일 한도: 10,000건/일 (openapi.krx.co.kr 정책, DART 카운터와 독립)
응답 포맷: JSON, 키 "OutBlock_1" 아래 list
엔드포인트: https://data-dbg.krx.co.kr/svc/apis/
"""

import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from utils import DATA_RAW, append_to_csv, load_checkpoint, mark_completed, save_checkpoint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
KRX_API_BASE = "https://data-dbg.krx.co.kr/svc/apis"
KRX_SLEEP_SEC = 0.5          # 호출 간 대기
FIND_TRADING_DAY_SLEEP = 0.3  # 거래일 탐색 시 대기

CHECKPOINT_PATH = DATA_RAW / "market_cap_checkpoint.json"
OUTPUT_PATH = DATA_RAW / "market_cap_raw.csv"
YEARS = list(range(2015, 2026))
FIELDNAMES = [
    "corp_code", "corp_name", "stock_code", "market",
    "year", "snapshot_date", "market_cap", "shares",
]

# KRX OpenAPI 응답 필드명 (data-dbg.krx.co.kr 확인 필드)
# ISU_SRT_CD: 6자리 단축 종목코드, MKTCAP: 시가총액(원), LIST_SHRS: 상장주식수
KRX_FIELD_TICKER = "ISU_SRT_CD"
KRX_FIELD_MKTCAP = "MKTCAP"
KRX_FIELD_SHARES = "LIST_SHRS"

# KOSPI / KOSDAQ 별도 엔드포인트
ENDPOINTS = [
    ("sto/stk_bydd_trd", "KOSPI"),
    ("sto/ksq_bydd_trd", "KOSDAQ"),
]


def _check_krx_credentials() -> str:
    """KRX_AUTH_KEY 환경변수 확인. 없으면 명확한 오류 메시지로 종료."""
    load_dotenv(BASE_DIR / ".env")
    key = os.environ.get("KRX_AUTH_KEY")
    if not key:
        raise RuntimeError(
            "KRX_AUTH_KEY 환경변수 미설정\n"
            "  로컬: .env 에 KRX_AUTH_KEY=... 추가\n"
            "  CI  : GitHub Settings → Secrets → KRX_AUTH_KEY 등록\n"
            "  발급: https://openapi.krx.co.kr (마이페이지 > API 인증키 신청)"
        )
    return key


def _parse_number(val: object) -> int | str:
    """KRX 응답 숫자 문자열(콤마 포함) → int. 빈 값은 빈 문자열 반환."""
    if val is None or str(val).strip() in ("", "-"):
        return ""
    try:
        return int(str(val).replace(",", "").strip())
    except ValueError:
        return ""


def call_krx_api(endpoint: str, auth_key: str, params: dict) -> list[dict]:
    """KRX OpenAPI 단건 호출. OutBlock_1 리스트 반환."""
    url = f"{KRX_API_BASE}/{endpoint}"
    full_params = {"AUTH_KEY": auth_key, **params}
    try:
        resp = requests.get(url, params=full_params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("OutBlock_1", [])
        if not isinstance(result, list):
            logger.warning(f"[KRX] OutBlock_1 비정상 타입: {type(result)}")
            return []
        return result
    except requests.RequestException as e:
        logger.error(f"[KRX] HTTP 오류 ({endpoint}): {e}")
        return []
    except ValueError as e:
        logger.error(f"[KRX] JSON 파싱 오류 ({endpoint}): {e}")
        return []


def find_last_trading_day(year: int, auth_key: str) -> str:
    """해당 연도의 마지막 거래일을 YYYYMMDD로 반환.

    12/31부터 역순으로 최대 15일 탐색. KOSPI 엔드포인트 응답이 비면 휴장으로 판단.
    """
    today = date.today()
    candidate = date(year, 12, 31)
    if candidate > today:
        candidate = today

    for _ in range(15):
        dt_str = candidate.strftime("%Y%m%d")
        rows = call_krx_api("sto/stk_bydd_trd", auth_key, {"basDd": dt_str})
        if rows:
            return dt_str
        candidate -= timedelta(days=1)
        time.sleep(FIND_TRADING_DAY_SLEEP)

    raise RuntimeError(f"{year}년 마지막 거래일을 찾지 못했습니다 (15일 탐색 실패)")


def collect_year(year: int, corps: pd.DataFrame, auth_key: str) -> int:
    """해당 연도 연말 시가총액을 KOSPI + KOSDAQ 모두 수집. 저장 행수 반환."""
    snapshot_date = find_last_trading_day(year, auth_key)
    logger.info(f"[{year}] 스냅샷 거래일: {snapshot_date}")

    # KOSPI + KOSDAQ 각각 호출 후 합산
    all_records: list[dict] = []
    for endpoint, market_label in ENDPOINTS:
        rows = call_krx_api(endpoint, auth_key, {"basDd": snapshot_date})
        logger.info(f"[{year}] {market_label}: {len(rows)}종목 수신")

        for row in rows:
            ticker = str(row.get(KRX_FIELD_TICKER, "")).strip().zfill(6)
            if not ticker or ticker == "000000":
                continue
            all_records.append({
                "stock_code": ticker,
                "market_cap": _parse_number(row.get(KRX_FIELD_MKTCAP)),
                "shares": _parse_number(row.get(KRX_FIELD_SHARES)),
            })
        time.sleep(KRX_SLEEP_SEC)

    if not all_records:
        logger.warning(f"[{year}] KOSPI+KOSDAQ 모두 응답 비어있음 — 스킵")
        return 0

    # MKTCAP 필드 부재 경고 (응답 구조 변경 감지)
    sample = all_records[0] if all_records else {}
    if sample.get("market_cap") == "":
        logger.warning(
            f"[{year}] {KRX_FIELD_MKTCAP} 필드가 응답에 없거나 비어있습니다. "
            "KRX API 스펙 변경 여부 확인 필요."
        )

    df_krx = pd.DataFrame(all_records)
    df_krx["stock_code"] = df_krx["stock_code"].astype(str).str.zfill(6)
    # 중복 ticker 제거 (KOSPI/KOSDAQ 동시 상장 종목 등)
    df_krx = df_krx.drop_duplicates(subset="stock_code", keep="first")

    merged = corps.merge(df_krx, on="stock_code", how="inner")
    logger.info(
        f"[{year}] KRX {len(df_krx)}종목 ↔ 상장사 매칭 {len(merged)}/{len(corps)}"
    )

    output_rows = [
        {
            "corp_code": r["corp_code"],
            "corp_name": r["corp_name"],
            "stock_code": r["stock_code"],
            "market": r["market"],
            "year": str(year),
            "snapshot_date": snapshot_date,
            "market_cap": r["market_cap"],
            "shares": r["shares"],
        }
        for _, r in merged.iterrows()
    ]
    if output_rows:
        append_to_csv(OUTPUT_PATH, output_rows, FIELDNAMES)
    return len(output_rows)


def main() -> None:
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    auth_key = _check_krx_credentials()

    corps_path = DATA_RAW / "listed_corps.csv"
    if not corps_path.exists():
        raise FileNotFoundError(
            "listed_corps.csv가 없습니다. 먼저 01_get_corp_list.py를 실행하세요."
        )

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
            n_rows = collect_year(year, corps, auth_key)
            elapsed = (datetime.now() - t0).total_seconds()
            logger.info(f"[{year}] 저장 {n_rows}행 | 소요 {elapsed:.1f}초")

            mark_completed(checkpoint, "_ALL", str(year))
            save_checkpoint(CHECKPOINT_PATH, checkpoint)
            time.sleep(KRX_SLEEP_SEC)
    finally:
        save_checkpoint(CHECKPOINT_PATH, checkpoint)
        done = len(checkpoint.get("completed", {}).get("_ALL", []))
        logger.info(f"체크포인트 저장. 완료 연도: {done}/{len(YEARS)}")


if __name__ == "__main__":
    main()
