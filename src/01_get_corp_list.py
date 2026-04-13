#!/usr/bin/env python3
"""DART corpCode.xml에서 상장사 목록을 수집하여 CSV로 저장.

corpCode.xml에는 corp_cls 필드가 없으므로, stock_code가 있는 기업에 대해
company.json API를 호출하여 corp_cls(Y=KOSPI, K=KOSDAQ)를 확인한다.
일일 한도 고려: company.json 호출도 공유 카운터에 포함.
"""

import io
import json
import logging
import os
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import requests
from dotenv import load_dotenv

from utils import (
    BASE_DIR,
    DATA_RAW,
    SLEEP_SEC,
    call_dart_api,
    is_daily_limit_reached,
    load_api_key,
    load_daily_counter,
    save_daily_counter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# company.json 호출 체크포인트 (corp_code → corp_cls 매핑)
CLS_CHECKPOINT_PATH = DATA_RAW / "corp_cls_checkpoint.json"
# company.json 추가 필드 체크포인트 (corp_code → {est_dt, induty_code})
CORP_INFO_CHECKPOINT_PATH = DATA_RAW / "corp_info_checkpoint.json"


def download_corp_codes(api_key: str) -> list[dict[str, str]]:
    """corpCode.xml ZIP을 다운로드해 stock_code 있는 기업 목록 반환."""
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    logger.info("DART corpCode.xml ZIP 다운로드 중...")
    resp = requests.get(url, params={"crtfc_key": api_key}, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_name = zf.namelist()[0]
        with zf.open(xml_name) as f:
            tree = ElementTree.parse(f)

    rows = []
    for corp in tree.getroot().iter("list"):
        stock_code = corp.findtext("stock_code", "").strip()
        if not stock_code:
            continue
        rows.append({
            "corp_code": corp.findtext("corp_code", "").strip(),
            "corp_name": corp.findtext("corp_name", "").strip(),
            "stock_code": stock_code,
        })

    logger.info(f"stock_code 있는 기업 {len(rows)}개 파싱")
    return rows


def load_cls_checkpoint() -> dict[str, str]:
    """corp_code → corp_cls 매핑 체크포인트 로드."""
    if CLS_CHECKPOINT_PATH.exists():
        return json.loads(CLS_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {}


def save_cls_checkpoint(mapping: dict[str, str]) -> None:
    CLS_CHECKPOINT_PATH.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_corp_info_checkpoint() -> dict[str, dict[str, str]]:
    """corp_code → {est_dt, induty_code} 체크포인트 로드."""
    if CORP_INFO_CHECKPOINT_PATH.exists():
        return json.loads(CORP_INFO_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {}


def save_corp_info_checkpoint(mapping: dict[str, dict[str, str]]) -> None:
    CORP_INFO_CHECKPOINT_PATH.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_corp_cls(
    corps: list[dict[str, str]],
    api_key: str,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """company.json API로 corp_cls·est_dt·induty_code 확인. 체크포인트 지원."""
    cls_map = load_cls_checkpoint()
    info_map = load_corp_info_checkpoint()
    # cls_map OR info_map 중 하나라도 누락된 기업은 재조회 대상
    # (이전 실행이 corp_cls만 저장하고 info는 수집 안했을 가능성 대비)
    remaining = [
        c for c in corps
        if c["corp_code"] not in cls_map or c["corp_code"] not in info_map
    ]

    already_done = len(corps) - len(remaining)
    counter = load_daily_counter()
    logger.info(
        f"corp_cls 조회 대상: {len(remaining)}개 "
        f"(이미 완료: {already_done}개) | "
        f"오늘 API 호출: {counter['calls']}/{10_000}"
    )

    try:
        for i, corp in enumerate(remaining):
            if is_daily_limit_reached(counter):
                logger.warning(
                    f"일일 한도 도달 — corp_cls 조회 {len(remaining) - i}개 미완료. "
                    "내일 재실행하면 이어서 진행됩니다."
                )
                break

            data = call_dart_api("company", api_key, {"corp_code": corp["corp_code"]})
            counter["calls"] += 1
            # cls_map 은 이미 있으면 덮어쓰지 않음 (값 있는 결과 보존)
            if corp["corp_code"] not in cls_map:
                cls_map[corp["corp_code"]] = data.get("corp_cls", "") if data else ""
            # info_map 은 매번 갱신 (신규 필드 추가 목적)
            info_map[corp["corp_code"]] = {
                "est_dt": data.get("est_dt", "") if data else "",
                "induty_code": data.get("induty_code", "") if data else "",
            }

            if (i + 1) % 100 == 0:
                save_cls_checkpoint(cls_map)
                save_corp_info_checkpoint(info_map)
                save_daily_counter(counter)
                logger.info(f"  corp_cls 조회 {i + 1}/{len(remaining)} | 오늘 호출: {counter['calls']}")

            time.sleep(SLEEP_SEC)

    finally:
        save_cls_checkpoint(cls_map)
        save_corp_info_checkpoint(info_map)
        save_daily_counter(counter)

    return cls_map, info_map


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        raise RuntimeError("DART_API_KEY가 .env에 설정되지 않았습니다.")

    DATA_RAW.mkdir(parents=True, exist_ok=True)

    # Phase 1: corpCode.xml 다운로드
    corps = download_corp_codes(api_key)

    # Phase 2: company.json으로 corp_cls·est_dt·induty_code 확인 (체크포인트 지원)
    cls_map, info_map = fetch_corp_cls(corps, api_key)

    # Phase 3: KOSPI/KOSDAQ만 필터 후 저장
    market_map = {"Y": "KOSPI", "K": "KOSDAQ"}
    rows = []
    for corp in corps:
        corp_cls = cls_map.get(corp["corp_code"], "")
        market = market_map.get(corp_cls)
        if market is None:
            continue
        info = info_map.get(corp["corp_code"], {})
        rows.append({
            **corp,
            "market": market,
            "est_dt": info.get("est_dt", ""),
            "induty_code": info.get("induty_code", ""),
        })

    df = pd.DataFrame(rows)

    if df.empty:
        # corp_cls 조회가 아직 미완료인 경우 — 지금까지 얻은 결과만 저장
        logger.warning(
            "KOSPI/KOSDAQ 기업이 0개입니다. "
            "corp_cls 조회가 완료되지 않았을 수 있습니다. "
            "내일 재실행하세요."
        )
        # 그래도 현재까지 분류된 결과로 부분 저장
        rows_partial = []
        for corp in corps:
            corp_cls = cls_map.get(corp["corp_code"])
            if corp_cls is None:
                continue  # 아직 조회 안 됨
            market = market_map.get(corp_cls)
            if market:
                info = info_map.get(corp["corp_code"], {})
                rows_partial.append({
                    **corp,
                    "market": market,
                    "est_dt": info.get("est_dt", ""),
                    "induty_code": info.get("induty_code", ""),
                })
        if rows_partial:
            df = pd.DataFrame(rows_partial)

    out_path = DATA_RAW / "listed_corps.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    counts = df["market"].value_counts() if not df.empty else {}
    logger.info("=== 상장사 통계 ===")
    logger.info(f"  KOSPI : {counts.get('KOSPI', 0)}개")
    logger.info(f"  KOSDAQ: {counts.get('KOSDAQ', 0)}개")
    logger.info(f"  합계  : {len(df)}개")
    logger.info(f"저장: {out_path}")

    remaining_unclassified = sum(
        1 for c in corps if c["corp_code"] not in cls_map
    )
    if remaining_unclassified:
        logger.warning(f"미분류 기업 {remaining_unclassified}개 — 내일 재실행 필요")


if __name__ == "__main__":
    main()
