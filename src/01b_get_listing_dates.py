#!/usr/bin/env python3
"""KRX에서 상장일(isu_dt) 수집하여 listed_corps.csv에 병합.

DART company.json에는 상장일이 없으므로 KRX KIND 다운로드 API로
종목별 상장일을 수집한다. KIND 실패 시 FinanceDataReader 폴백 시도.

H1 가설 검증에 필요한 post2014 더미 변수 생성에 사용.
"""

import logging
import re
import sys
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"

DATE_PATTERN = re.compile(r"^\d{8}$")


def fetch_listing_dates_krx_kind() -> pd.DataFrame:
    """KRX KIND 다운로드 API로 전체 상장법인 + 상장일 수집.

    KIND URL: https://kind.krx.co.kr/corpgeneral/corpList.do?method=download
    응답은 HTML 테이블 (EUC-KR 인코딩). lxml 또는 html5lib 필요.
    """
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do"
    params = {"method": "download"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    logger.info("KRX KIND에서 전체 상장법인 목록 다운로드 시도...")
    resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()

    # 응답 일부 로깅 (디버깅용)
    logger.info(f"  응답 크기: {len(resp.content)} bytes, Content-Type: {resp.headers.get('Content-Type','?')}")

    # HTML 테이블 파싱 — lxml 우선, 실패 시 bs4 폴백
    try:
        tables = pd.read_html(resp.content, encoding="euc-kr", flavor="lxml")
    except (ValueError, ImportError) as e:
        logger.warning(f"  lxml 파싱 실패 ({e}), bs4로 재시도")
        tables = pd.read_html(resp.content, encoding="euc-kr", flavor="bs4")

    if not tables:
        raise RuntimeError("KRX 응답에 HTML 테이블이 없습니다.")

    df = tables[0]
    logger.info(f"  KIND 다운로드 성공: {len(df)}행, 컬럼: {list(df.columns)}")
    return df


def fetch_listing_dates_fdr() -> pd.DataFrame:
    """FinanceDataReader 폴백. KIND 실패 시 사용."""
    try:
        import FinanceDataReader as fdr
    except ImportError:
        logger.warning("FinanceDataReader 미설치 — 폴백 불가")
        return pd.DataFrame()

    logger.info("FinanceDataReader로 KRX 상장일 조회 시도...")
    df = fdr.StockListing("KRX")
    logger.info(f"  FDR 조회 성공: {len(df)}행, 컬럼: {list(df.columns)}")
    return df


def normalize_date(val: str) -> str:
    """YYYY-MM-DD 또는 YYYYMMDD 등 → YYYYMMDD. 유효하지 않으면 빈 문자열."""
    if pd.isna(val):
        return ""
    s = str(val).strip().replace("-", "").replace("/", "").replace(".", "")
    if DATE_PATTERN.match(s):
        return s
    return ""


def extract_stock_code_and_date(df_krx: pd.DataFrame) -> pd.DataFrame:
    """KRX 응답 DataFrame에서 stock_code, isu_dt 컬럼만 추출하여 정규화."""
    if df_krx.empty:
        return pd.DataFrame(columns=["stock_code", "isu_dt"])

    col_map: dict[str, str] = {}
    for col in df_krx.columns:
        cl = str(col).strip()
        if ("종목코드" in cl) or ("단축코드" in cl) or (cl.lower() in ("code", "symbol")):
            col_map.setdefault("stock_code", col)
        elif ("상장일" in cl) or ("상장" == cl) or (cl.lower() in ("listingdate", "listing_date", "isu_dt")):
            col_map.setdefault("isu_dt", col)

    if "stock_code" not in col_map or "isu_dt" not in col_map:
        raise RuntimeError(
            f"KRX 응답에서 stock_code/isu_dt 컬럼을 찾지 못함. 실제 컬럼: {list(df_krx.columns)}"
        )

    df = df_krx[[col_map["stock_code"], col_map["isu_dt"]]].copy()
    df.columns = ["stock_code", "isu_dt"]
    df["stock_code"] = df["stock_code"].astype(str).str.strip().str.zfill(6)
    df["isu_dt"] = df["isu_dt"].apply(normalize_date)
    # 빈 문자열은 NaN으로
    df["isu_dt"] = df["isu_dt"].where(df["isu_dt"] != "", pd.NA)
    return df


def main() -> None:
    listed_path = DATA_RAW / "listed_corps.csv"
    if not listed_path.exists():
        raise FileNotFoundError("listed_corps.csv가 없습니다. 먼저 01_get_corp_list.py를 실행하세요.")

    df_corps = pd.read_csv(listed_path, dtype=str)
    logger.info(f"상장사 {len(df_corps)}개 로드")

    # 1차: KIND 다운로드
    df_krx = pd.DataFrame()
    try:
        df_krx = fetch_listing_dates_krx_kind()
    except Exception:
        logger.exception("KRX KIND 다운로드 실패")

    # 컬럼 추출 시도
    df_krx_slim = pd.DataFrame()
    if not df_krx.empty:
        try:
            df_krx_slim = extract_stock_code_and_date(df_krx)
        except Exception:
            logger.exception("KIND 응답 컬럼 추출 실패")

    # 2차 폴백: FinanceDataReader
    if df_krx_slim.empty or df_krx_slim["isu_dt"].notna().sum() == 0:
        logger.warning("KIND 실패 또는 상장일 결측 → FinanceDataReader 폴백 시도")
        try:
            df_fdr = fetch_listing_dates_fdr()
            if not df_fdr.empty:
                # fdr StockListing 컬럼: Code, Name, Market, ListingDate 등
                if "ListingDate" in df_fdr.columns:
                    df_krx_slim = df_fdr[["Code", "ListingDate"]].copy()
                    df_krx_slim.columns = ["stock_code", "isu_dt"]
                    df_krx_slim["stock_code"] = df_krx_slim["stock_code"].astype(str).str.strip().str.zfill(6)
                    df_krx_slim["isu_dt"] = df_krx_slim["isu_dt"].apply(normalize_date)
                    df_krx_slim["isu_dt"] = df_krx_slim["isu_dt"].where(df_krx_slim["isu_dt"] != "", pd.NA)
        except Exception:
            logger.exception("FinanceDataReader 폴백 실패")

    # 최종 확인: 상장일 데이터가 하나라도 있어야 함
    valid_count = df_krx_slim["isu_dt"].notna().sum() if not df_krx_slim.empty else 0
    if valid_count == 0:
        logger.error("❌ KIND/FDR 모두 실패. isu_dt 수집 불가.")
        sys.exit(1)

    logger.info(f"KRX 상장일 데이터: {valid_count}개 유효")

    # listed_corps.csv와 조인
    df_corps["stock_code"] = df_corps["stock_code"].astype(str).str.strip().str.zfill(6)
    df_merged = df_corps.merge(df_krx_slim, on="stock_code", how="left")

    matched = df_merged["isu_dt"].notna().sum()
    logger.info(f"상장일 매칭: {matched}/{len(df_merged)}개 ({matched/len(df_merged)*100:.1f}%)")

    if matched == 0:
        logger.error("❌ 매칭 0건. stock_code 형식 확인 필요.")
        logger.error(f"  KRX stock_code 샘플: {df_krx_slim['stock_code'].head(3).tolist()}")
        logger.error(f"  corps stock_code 샘플: {df_corps['stock_code'].head(3).tolist()}")
        sys.exit(1)

    df_merged.to_csv(listed_path, index=False, encoding="utf-8-sig")
    logger.info(f"저장 완료: {listed_path}")
    logger.info(f"  isu_dt 샘플: {df_merged['isu_dt'].dropna().head(3).tolist()}")


if __name__ == "__main__":
    main()
