#!/usr/bin/env python3
"""DART corpCode.xml에서 상장사 목록을 수집하여 CSV로 저장."""

import io
import logging
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import requests
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"


def get_corp_list(api_key: str) -> pd.DataFrame:
    """DART corpCode.xml ZIP을 다운로드하여 상장사 목록을 반환."""
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": api_key}

    logger.info("DART corpCode.xml ZIP 다운로드 중...")
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_name = zf.namelist()[0]
        with zf.open(xml_name) as f:
            tree = ElementTree.parse(f)

    root = tree.getroot()
    rows: list[dict[str, str]] = []
    for corp in root.iter("list"):
        corp_code = corp.findtext("corp_code", "").strip()
        corp_name = corp.findtext("corp_name", "").strip()
        stock_code = corp.findtext("stock_code", "").strip()
        corp_cls = corp.findtext("corp_cls", "").strip()

        if not stock_code:
            continue

        market_map = {"Y": "KOSPI", "K": "KOSDAQ"}
        market = market_map.get(corp_cls)
        if market is None:
            continue

        rows.append({
            "corp_code": corp_code,
            "corp_name": corp_name,
            "stock_code": stock_code,
            "market": market,
        })

    df = pd.DataFrame(rows)
    logger.info(f"총 {len(df)}개 상장사 파싱 완료")
    return df


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        raise RuntimeError("DART_API_KEY가 .env에 설정되지 않았습니다.")

    df = get_corp_list(api_key)

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    out_path = DATA_RAW / "listed_corps.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info(f"저장: {out_path}")

    # 통계 출력
    counts = df["market"].value_counts()
    logger.info("=== 상장사 통계 ===")
    logger.info(f"  KOSPI : {counts.get('KOSPI', 0)}개")
    logger.info(f"  KOSDAQ: {counts.get('KOSDAQ', 0)}개")
    logger.info(f"  합계  : {len(df)}개")


if __name__ == "__main__":
    main()
