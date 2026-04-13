#!/usr/bin/env python3
"""KRX에서 상장일(isu_dt) 수집하여 listed_corps.csv에 병합.

DART company.json에는 상장일이 없으므로 pykrx 라이브러리를 통해
KRX에서 종목별 상장일을 수집한다.

H1 가설 검증에 필요한 post2014 더미 변수 생성에 사용.
"""

import logging
import time
from pathlib import Path

import pandas as pd

try:
    from pykrx import stock as krx_stock
except ImportError:
    raise ImportError("pykrx가 설치되어 있지 않습니다. pip install pykrx 실행 후 재시도하세요.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"


def get_listing_date(ticker: str) -> str:
    """pykrx로 종목 상장일 조회. 실패 시 빈 문자열 반환."""
    try:
        time.sleep(0.1)  # KRX 서버 부하 방지
        info = krx_stock.get_market_cap_by_date(
            fromdate="20000101",
            todate="20000101",
            ticker=ticker,
        )
        # pykrx의 listing date 조회
        df = krx_stock.get_market_fundamental_by_date(
            fromdate="19900101",
            todate="19900101",
            ticker=ticker,
        )
        return ""
    except Exception:
        return ""


def fetch_listing_dates_pykrx(tickers: list[str]) -> dict[str, str]:
    """pykrx로 전체 종목의 상장일 조회.

    pykrx의 get_market_ticker_list()로 현재 상장 종목 + 상장일을 가져옴.
    """
    logger.info("KRX 전체 상장 종목 목록 조회 중...")

    # KOSPI + KOSDAQ 전체 목록 (현재 상장 + 상장폐지 포함 시 get_market_ticker_list 사용)
    # pykrx는 특정 날짜의 상장 종목 목록만 제공하므로, 과거 상장폐지 종목은 누락될 수 있음
    results = {}

    try:
        # 시장별 현재 상장 종목 목록
        for market in ["KOSPI", "KOSDAQ"]:
            tickers_in_market = krx_stock.get_market_ticker_list(market=market)
            logger.info(f"  {market}: {len(tickers_in_market)}개 종목")

            for i, ticker in enumerate(tickers_in_market):
                try:
                    # pykrx: 종목의 상장일 정보는 직접 제공하지 않음
                    # KRX 기업 정보에서 상장일 추출 시도
                    time.sleep(0.05)
                    # get_market_ticker_name 등의 API는 상장일 미제공
                    # 실제 상장일: KRX의 종목 상세 정보 페이지에서만 제공
                except Exception:
                    pass

                if (i + 1) % 100 == 0:
                    logger.info(f"  {market} 처리: {i + 1}/{len(tickers_in_market)}")

    except Exception as e:
        logger.error(f"KRX 조회 오류: {e}")

    return results


def fetch_listing_dates_krx_download() -> pd.DataFrame:
    """KRX KIND 다운로드 API로 전체 종목 목록 + 상장일 수집.

    KRX KIND (kind.krx.co.kr)에서 제공하는 CSV 다운로드를 활용.
    URL: https://kind.krx.co.kr/corpgeneral/corpList.do?method=download
    반환: stock_code, corp_name, isu_dt (상장일) 컬럼
    """
    import requests

    url = "https://kind.krx.co.kr/corpgeneral/corpList.do"
    params = {
        "method": "download",
        "searchType": "13",  # 전체 상장 법인
    }

    logger.info("KRX KIND에서 전체 상장법인 목록 다운로드 중...")
    try:
        resp = requests.get(url, params=params, timeout=30,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        # 응답이 EUC-KR 인코딩
        df = pd.read_html(resp.content, encoding="euc-kr")[0]
        logger.info(f"  다운로드 완료: {len(df)}행")
        logger.info(f"  컬럼: {list(df.columns)}")
        return df
    except Exception as e:
        logger.error(f"KRX KIND 다운로드 오류: {e}")
        return pd.DataFrame()


def main() -> None:
    listed_path = DATA_RAW / "listed_corps.csv"
    if not listed_path.exists():
        raise FileNotFoundError("listed_corps.csv가 없습니다. 먼저 01_get_corp_list.py를 실행하세요.")

    df_corps = pd.read_csv(listed_path, dtype=str)
    logger.info(f"상장사 {len(df_corps)}개 로드")

    # KRX KIND 다운로드로 상장일 수집
    df_krx = fetch_listing_dates_krx_download()

    if df_krx.empty:
        logger.error("KRX 데이터 수집 실패 — isu_dt 없이 listed_corps.csv 유지")
        return

    # 컬럼명 정규화 (KRX 응답의 실제 컬럼명 확인 후 매핑)
    logger.info(f"KRX 컬럼: {list(df_krx.columns)}")

    # 일반적으로 KRX KIND에서 내려오는 컬럼: 회사명, 종목코드, 업종, 주요제품, 상장일, 결산월, 대표자명, 홈페이지, 지역
    col_map = {}
    for col in df_krx.columns:
        col_lower = str(col).strip()
        if "종목코드" in col_lower or "단축코드" in col_lower:
            col_map["stock_code"] = col
        elif "상장일" in col_lower:
            col_map["isu_dt"] = col
        elif "회사명" in col_lower or "기업명" in col_lower:
            col_map["corp_name_krx"] = col

    if "stock_code" not in col_map or "isu_dt" not in col_map:
        logger.error(f"필요한 컬럼 없음. 실제 컬럼: {list(df_krx.columns)}")
        return

    df_krx_slim = df_krx[[col_map["stock_code"], col_map["isu_dt"]]].copy()
    df_krx_slim.columns = ["stock_code", "isu_dt"]
    df_krx_slim["stock_code"] = df_krx_slim["stock_code"].astype(str).str.zfill(6)
    df_krx_slim["isu_dt"] = df_krx_slim["isu_dt"].astype(str).str.replace("-", "").str.strip()

    # listed_corps.csv의 stock_code와 조인
    df_corps["stock_code"] = df_corps["stock_code"].astype(str).str.zfill(6)
    df_merged = df_corps.merge(df_krx_slim, on="stock_code", how="left")

    matched = df_merged["isu_dt"].notna().sum()
    logger.info(f"상장일 매칭: {matched}/{len(df_merged)}개 ({matched/len(df_merged)*100:.1f}%)")

    # 기존 listed_corps.csv에 isu_dt 컬럼 추가 저장
    df_merged.to_csv(listed_path, index=False, encoding="utf-8-sig")
    logger.info(f"저장 완료: {listed_path}")
    logger.info(f"  isu_dt 샘플: {df_merged['isu_dt'].dropna().head(3).tolist()}")


if __name__ == "__main__":
    main()
