#!/usr/bin/env python3
"""공통 유틸리티: 체크포인트, API 호출, CSV 저장, 일일 카운터."""

import csv
import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"

DAILY_LIMIT = 10_000
SLEEP_SEC = 0.5
API_BASE = "https://opendart.fss.or.kr/api"

# 모든 수집 스크립트가 공유하는 일일 API 호출 카운터 경로
DAILY_COUNTER_PATH = DATA_RAW / ".api_daily_counter.json"


# ─── API 키 ─────────────────────────────────────────────────────────────────

def load_api_key() -> str:
    """DART_API_KEY를 .env에서 로드."""
    load_dotenv(BASE_DIR / ".env")
    key = os.getenv("DART_API_KEY")
    if not key:
        raise RuntimeError("DART_API_KEY가 .env에 설정되지 않았습니다.")
    return key


# ─── 일일 API 호출 카운터 (스크립트 간 공유) ────────────────────────────────

def load_daily_counter() -> dict[str, Any]:
    """공유 일일 카운터 로드. 날짜가 달라지면 자동 리셋."""
    if DAILY_COUNTER_PATH.exists():
        data = json.loads(DAILY_COUNTER_PATH.read_text(encoding="utf-8"))
        if data.get("date") != str(date.today()):
            logger.info(f"날짜 변경 → 일일 카운터 리셋 (이전: {data.get('date')})")
            return {"date": str(date.today()), "calls": 0}
        return data
    return {"date": str(date.today()), "calls": 0}


def save_daily_counter(counter: dict[str, Any]) -> None:
    """공유 일일 카운터 저장."""
    counter["date"] = str(date.today())
    DAILY_COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAILY_COUNTER_PATH.write_text(
        json.dumps(counter, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_daily_limit_reached(counter: dict[str, Any]) -> bool:
    return counter["calls"] >= DAILY_LIMIT


# ─── 체크포인트 ──────────────────────────────────────────────────────────────

def load_checkpoint(path: Path) -> dict[str, Any]:
    """체크포인트 JSON 로드. 없으면 빈 상태 반환.

    completed 형식: {corp_code: [year, ...], ...}
    (이전 버전 list-of-pairs 형식도 자동 변환)
    """
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            cp = json.load(f)

        # ── 구 형식(list) → 신 형식(dict) 자동 변환 ──
        if isinstance(cp.get("completed"), list):
            new_completed: dict[str, list[str]] = {}
            for item in cp["completed"]:
                corp_code, year = str(item[0]), str(item[1])
                new_completed.setdefault(corp_code, [])
                if year not in new_completed[corp_code]:
                    new_completed[corp_code].append(year)
            cp["completed"] = new_completed
            logger.info("체크포인트 형식 변환 완료 (list → dict)")

        return cp

    return {"completed": {}, "date": str(date.today())}


def save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    """체크포인트 JSON 저장."""
    checkpoint["date"] = str(date.today())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def mark_completed(checkpoint: dict[str, Any], corp_code: str, year: str) -> None:
    """체크포인트에 완료 항목 추가."""
    completed = checkpoint.setdefault("completed", {})
    completed.setdefault(corp_code, [])
    if year not in completed[corp_code]:
        completed[corp_code].append(year)


def is_completed(checkpoint: dict[str, Any], corp_code: str, year: str) -> bool:
    """해당 (corp_code, year) 조합이 이미 완료됐는지 확인."""
    return year in checkpoint.get("completed", {}).get(corp_code, [])


# ─── DART API 호출 (재시도 내장) ──────────────────────────────────────────────

def call_dart_api(
    endpoint: str,
    api_key: str,
    params: dict[str, str],
    max_retries: int = 3,
) -> dict | None:
    """DART API 호출.

    Returns:
        성공(status=000) → dict
        조회 결과 없음(status=013) → None
        오류 → None  (최대 max_retries 재시도 후)
    """
    url = f"{API_BASE}/{endpoint}.json"
    call_params = {**params, "crtfc_key": api_key}

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=call_params, timeout=30)

            # 레이트 리밋 응답 → 60초 대기 후 재시도
            if resp.status_code == 429:
                logger.warning("레이트 리밋(429) → 60초 대기")
                time.sleep(60)
                continue

            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")

            if status == "000":
                return data
            elif status == "013":
                return None  # 조회 결과 없음 — 정상
            else:
                logger.warning(
                    f"API 에러: status={status}, "
                    f"message={data.get('message', '')}, "
                    f"endpoint={endpoint}, params={params}"
                )
                return None  # 비정상 응답 — 재시도 불필요

        except requests.ConnectionError as e:
            wait = 2 ** attempt
            if attempt < max_retries - 1:
                logger.warning(f"연결 오류 (시도 {attempt + 1}/{max_retries}) → {wait}초 대기: {e}")
                time.sleep(wait)
            else:
                logger.error(f"연결 오류 최대 재시도 초과: {e}")
                return None

        except requests.RequestException as e:
            logger.error(f"HTTP 오류: {e}")
            return None

    return None


# ─── CSV 유틸 ────────────────────────────────────────────────────────────────

def append_to_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """CSV 파일에 행 추가. 파일 없으면 헤더 포함 생성."""
    file_exists = path.exists() and path.stat().st_size > 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
