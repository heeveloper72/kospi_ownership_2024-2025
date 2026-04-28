#!/usr/bin/env python3
"""재무데이터 + 시가총액 병합 → Tobin Q 및 통제변수 계산 (H1·H3·H5 공통).

입력:
  data/raw/financial_raw.csv   — Step 8 (DART fnlttSinglAcntAll)
  data/raw/market_cap_raw.csv  — Step 9 (KRX 연말 시가총액)

출력:
  data/processed/financial_panel.csv — 기업-연도 패널

변수 정의:
  tobin_q        = (market_cap + total_liabilities) / total_assets
                   * Chung & Pruitt(1994) 간편 추정. total_assets > 0만 계산.
  leverage       = total_liabilities / total_assets  (부채비율 0~1)
  size           = ln(total_assets / 1e8)            (억원 단위 로그, 표준 통제변수)
  roa            = operating_income / total_assets   (자산영업이익률)
  roe            = operating_income / total_equity   (total_equity > 0만 계산)
  market_to_book = market_cap / total_equity         (총자본 대비 시가, total_equity > 0)
  fs_div_used    = CFS / OFS / NONE                  (재무제표 구분)
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROCESSED = BASE_DIR / "data" / "processed"

FIELDNAMES = [
    "corp_code", "corp_name", "market", "year", "fs_div_used",
    "total_assets", "total_liabilities", "total_equity",
    "revenue", "operating_income",
    "market_cap", "shares", "snapshot_date",
    "tobin_q", "leverage", "size", "roa", "roe", "market_to_book",
]


def _parse_amount(val: object) -> float:
    """DART 금액 문자열(원, 콤마 포함) → float. 변환 불가 시 NaN."""
    if pd.isna(val):
        return np.nan
    s = str(val).strip().replace(",", "").replace(" ", "")
    if s in ("", "-"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def _parse_market_cap(val: object) -> float:
    """KRX 시가총액(콤마 포함 문자열 또는 숫자) → float."""
    if pd.isna(val):
        return np.nan
    s = str(val).strip().replace(",", "").replace(" ", "")
    if s in ("", "-"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def load_financial() -> pd.DataFrame:
    path = DATA_RAW / "financial_raw.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 없음 — Step 8(08_collect_financial.py)을 먼저 실행하세요."
        )
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    # BOM 제거 방어 — 컬럼명에 ﻿ 포함 가능성
    df.columns = [c.lstrip("﻿").strip() for c in df.columns]
    logger.info(f"financial_raw.csv: {len(df):,}행, 컬럼: {list(df.columns)[:6]}")

    for col in ["total_assets", "total_liabilities", "total_equity", "revenue", "operating_income"]:
        if col not in df.columns:
            logger.warning(f"  컬럼 누락: {col} — NaN으로 채움")
            df[col] = np.nan
        df[col] = df[col].apply(_parse_amount)

    # (corp_code, year) 중복 시 total_assets 큰 행 우선 (연결/개별 혼재 방어)
    before = len(df)
    df = df.sort_values("total_assets", ascending=False, na_position="last")
    df = df.drop_duplicates(subset=["corp_code", "year"], keep="first")
    if len(df) < before:
        logger.info(f"  중복 제거: {before - len(df):,}행 → {len(df):,}행")

    df["year"] = df["year"].astype(str)
    return df


def load_market_cap() -> pd.DataFrame:
    path = DATA_RAW / "market_cap_raw.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 없음 — Step 9(09_collect_market_cap.py)를 먼저 실행하세요."
        )
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    df.columns = [c.lstrip("﻿").strip() for c in df.columns]
    logger.info(f"market_cap_raw.csv: {len(df):,}행, 컬럼: {list(df.columns)}")

    for col in ["market_cap", "shares"]:
        if col not in df.columns:
            logger.warning(f"  컬럼 누락: {col} — NaN으로 채움")
            df[col] = np.nan
    df["market_cap"] = df["market_cap"].apply(_parse_market_cap)
    df["shares"] = df["shares"].apply(_parse_market_cap)
    df["year"] = df["year"].astype(str)

    # (corp_code, year) 중복 제거 (시가총액 큰 행 우선)
    before = len(df)
    df = df.sort_values("market_cap", ascending=False, na_position="last")
    df = df.drop_duplicates(subset=["corp_code", "year"], keep="first")
    if len(df) < before:
        logger.info(f"  market_cap 중복 제거: {before - len(df):,}행 → {len(df):,}행")

    return df[["corp_code", "year", "market_cap", "shares", "snapshot_date"]]


def compute_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """재무비율 계산. 분모 0 또는 음수일 때 NaN 처리."""
    a = df["total_assets"]
    l = df["total_liabilities"]
    e = df["total_equity"]
    oi = df["operating_income"]
    mc = df["market_cap"]

    # 분모 0·음수·NaN 방어
    valid_assets = a.where(a > 0)
    valid_equity = e.where(e > 0)

    df["tobin_q"] = (mc + l) / valid_assets
    df["leverage"] = l / valid_assets
    df["size"] = np.log(valid_assets / 1e8)   # 억원 단위 로그
    df["roa"] = oi / valid_assets
    df["roe"] = oi / valid_equity
    df["market_to_book"] = mc / valid_equity

    # 극단값 윈저라이징 (1%~99%) — 분석 전 사전 처리, 원본 보존용 NaN 아님
    for col in ["tobin_q", "leverage", "roa", "roe", "market_to_book"]:
        lo = df[col].quantile(0.01)
        hi = df[col].quantile(0.99)
        df[col] = df[col].clip(lower=lo, upper=hi)

    return df


def summarize(df: pd.DataFrame) -> None:
    logger.info("\n=== financial_panel.csv 요약 ===")
    logger.info(f"  총 관측치: {len(df):,}")
    logger.info(f"  연도 범위: {df['year'].min()} ~ {df['year'].max()}")
    for market in ["KOSPI", "KOSDAQ"]:
        cnt = (df["market"] == market).sum()
        logger.info(f"  {market}: {cnt:,}건")

    # market_cap 병합률
    mc_matched = df["market_cap"].notna().sum()
    logger.info(f"  시가총액 매칭: {mc_matched:,}/{len(df):,} ({mc_matched / len(df) * 100:.1f}%)")

    # Tobin Q 유효값
    tq_valid = df["tobin_q"].notna().sum()
    logger.info(f"  Tobin Q 유효값: {tq_valid:,}건")

    # 주요 변수 기술통계 (2023년)
    df23 = df[df["year"] == "2023"]
    if not df23.empty:
        logger.info("\n  === 2023년 기술통계 ===")
        for col in ["tobin_q", "leverage", "size", "roa"]:
            vals = df23[col].dropna()
            if len(vals) > 0:
                logger.info(
                    f"    {col}: mean={vals.mean():.3f} | median={vals.median():.3f} | "
                    f"std={vals.std():.3f} | n={len(vals):,}"
                )

    # CFS/OFS 구성
    fs_counts = df["fs_div_used"].value_counts()
    logger.info(f"\n  fs_div_used 분포: {fs_counts.to_dict()}")


def main() -> None:
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

    df_fin = load_financial()
    df_mcap = load_market_cap()

    # corp_code + year 기준 병합 (left join — 재무 기준, 시가총액 없는 연도 NaN 허용)
    df = df_fin.merge(df_mcap, on=["corp_code", "year"], how="left")
    logger.info(f"병합 후: {len(df):,}행")

    df = compute_ratios(df)

    # 컬럼 순서 정렬
    available_cols = [c for c in FIELDNAMES if c in df.columns]
    extra_cols = [c for c in df.columns if c not in FIELDNAMES]
    df = df[available_cols + extra_cols]

    output_path = DATA_PROCESSED / "financial_panel.csv"
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info(f"저장: {output_path}")

    summarize(df)

    # 소유구조 패널과 병합 가능 여부 확인
    ownership_path = DATA_PROCESSED / "ownership_panel.csv"
    if ownership_path.exists():
        df_own = pd.read_csv(ownership_path, dtype={"corp_code": str, "year": str}, encoding="utf-8-sig")
        df_own.columns = [c.lstrip("﻿").strip() for c in df_own.columns]
        merged = df_own.merge(
            df[["corp_code", "year", "tobin_q", "leverage", "size", "roa",
                "roe", "market_to_book", "market_cap", "total_assets"]],
            on=["corp_code", "year"], how="left",
        )
        out_merged = DATA_PROCESSED / "ownership_financial_panel.csv"
        merged.to_csv(out_merged, index=False, encoding="utf-8-sig")
        logger.info(f"\n소유구조+재무 통합 패널 저장: {out_merged}")
        logger.info(f"  {len(merged):,}행 | Tobin Q 매칭: {merged['tobin_q'].notna().sum():,}건")
    else:
        logger.warning("ownership_panel.csv 없음 — 통합 패널 생성 스킵 (Step 5 실행 후 재실행)")


if __name__ == "__main__":
    main()
