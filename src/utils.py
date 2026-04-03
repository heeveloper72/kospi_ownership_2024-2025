#!/usr/bin/env python3
"""공통 유틸리티: 체크포인트, API 호출, CSV 저장."""

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


def load_api_key() -> str:
    """DART_API_KEY를 .env에서 로드."""
    load_dotenv(BASE_DIR / ".env")
    key = os.getenv("DART_API_KEY")
    if not key:
        raise RuntimeError("DART_API_KEY가 .env에 설정되지 않았습니다.")
    return key


def load_checkpoint(path: Path) -> dict[str, Any]:
    """체크포인트 JSON 로드. 없으면 빈 상태 반환."""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            cp = json.load(f)
        # 날짜가 다르면 calls_today 리셋
        if cp.get("date") != str(date.today()):
            logger.info(f"날짜 변경 감지 → calls_today 리셋 (이전: {cp.get('date')})")
            cp["calls_today"] = 0
            cp["date"] = str(date.today())
        return cp
    return {
        "completed": [],
        "calls_today": 0,
        "date": str(date.today()),
    }


def save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    """체크포인트 JSON 저장."""
    checkpoint["date"] = str(date.today())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def call_dart_api(endpoint: str, api_key: str, params: dict[str, str]) -> dict | None:
    """DART API 호출. 성공 시 JSON dict, 실패 시 None 반환."""
    url = f"{API_BASE}/{endpoint}.json"
    params["crtfc_key"] = api_key

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status", "")
        if status == "000":
            return data
        elif status == "013":
            # 조회 결과 없음 — 정상 케이스
            return None
        else:
            logger.warning(f"API 에러: status={status}, message={data.get('message', '')}")
            return None
    except requests.RequestException as e:
        logger.error(f"HTTP 에러: {e}")
        return None


def append_to_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """CSV 파일에 행 추가. 파일 없으면 헤더 포함 생성."""
    file_exists = path.exists() and path.stat().st_size > 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
