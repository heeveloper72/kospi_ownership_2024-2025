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
인증 방식: HTTP 헤더 `AUTH_KEY: <key>` (URL 쿼리 파라미터 아님)

401 Unauthorized 시 점검 순서:
  1) 키에 개행/공백 섞였는지 (코드에서 strip 적용 중)
  2) KRX 마이페이지 > API 서비스 신청에서 주식(sto) 카테고리 이용신청 승인 여부
  3) 이용신청 승인까지 최대 1영업일 소요
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
    """KRX_AUTH_KEY 환경변수 확인. 없으면 명확한 오류 메시지로 종료.

    복사 붙여넣기 과정에서 섞이는 개행·공백을 strip() 으로 제거.
    """
    load_dotenv(BASE_DIR / ".env")
    key = os.environ.get("KRX_AUTH_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "KRX_AUTH_KEY 환경변수 미설정\n"
            "  로컬: .env 에 KRX_AUTH_KEY=... 추가\n"
            "  CI  : GitHub Settings → Secrets → KRX_AUTH_KEY 등록\n"
            "  발급: https://openapi.krx.co.kr (마이페이지 > API 인증키 신청)\n"
            "  추가 필수: 마이페이지 > API 서비스 신청 → 주식(sto) 카테고리 이용신청 승인"
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
    """KRX OpenAPI 단건 호출. OutBlock_1 리스트 반환.

    인증: AUTH_KEY를 HTTP 헤더로 전달 (URL 쿼리 파라미터 아님).
    401 응답 시: 키 자체가 아니라 서비스 이용신청 미승인 가능성 높음.
    """
    url = f"{KRX_API_BASE}/{endpoint}"
    headers = {"AUTH_KEY": auth_key}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code == 401:
            logger.error(
                f"[KRX] 401 Unauthorized ({endpoint}) — "
                "AUTH_KEY 유효성 또는 서비스 이용신청 승인 상태 확인 필요. "
                "KRX 마이페이지 > API 서비스 신청 > 주식(sto) 카테고리 승인 여부 점검."
            )
            return []
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
    401 응답이 반복되면 인증 문제로 간주하고 즉시 중단 (휴장 재시도 무의미).
    """
    today = date.today()
    candidate = date(year, 12, 31)
    if candidate > today:
        candidate = today

    consecutive_empty = 0
    for _ in range(15):
        dt_str = candidate.strftime("%Y%m%d")
        # 사전 검증: 첫 시도에서 401 나오면 인증 문제 — 빨리 중단
        url = f"{KRX_API_BASE}/sto/stk_bydd_trd"
        try:
            pre = requests.get(
                url, params={"basDd": dt_str},
                headers={"AUTH_KEY": auth_key}, timeout=30,
            )
            if pre.status_code == 401:
                raise RuntimeError(
                    f"KRX 401 Unauthorized (basDd={dt_str}). "
                    "AUTH_KEY 유효성 또는 서비스 이용신청 승인 상태 확인 필요. "
                    "마이페이지 > API 서비스 신청 > 주식(sto) 카테고리 승인 여부 점검."
                )
            if pre.status_code == 200:
                rows = pre.json().get("OutBlock_1", []) or []
                if rows:
                    return dt_str
                consecutive_empty += 1
        except requests.RequestException as e:
            logger.warning(f"[KRX] 거래일 탐색 중 오류 ({dt_str}): {e}")

        candidate -= timedelta(days=1)
        time.sleep(FIND_TRADING_DAY_SLEEP)

    raise RuntimeError(
        f"{year}년 마지막 거래일을 찾지 못했습니다 (15일 탐색 실패, "
        f"연속 빈 응답 {consecutive_empty}회). "
        "엔드포인트 또는 basDd 파라미터 형식 확인 필요."
    )


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
