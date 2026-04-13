#!/usr/bin/env python3
"""수집된 원시 데이터를 정제하고 병합하여 패널 데이터 생성."""

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


def parse_rate(s: str | float) -> float:
    """지분율 문자열을 float로 변환. 변환 불가 시 NaN."""
    if pd.isna(s):
        return np.nan
    s = str(s).strip().replace(",", "").replace("%", "")
    if s in ("", "-"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def process_ownership(df_own: pd.DataFrame) -> pd.DataFrame:
    """ownership_raw.csv에서 최대주주/특수관계인/우리사주 지분율 추출."""
    df_own["stock_rate_f"] = df_own["stock_rate"].apply(parse_rate)

    results = []
    for (corp_code, year), grp in df_own.groupby(["corp_code", "year"]):
        corp_name = grp["corp_name"].iloc[0]
        market = grp["market"].iloc[0]

        # 최대주주 본인: relate에 "본인" 포함
        mask_self = grp["relate"].str.contains("본인", na=False)
        largest_pct = grp.loc[mask_self, "stock_rate_f"].sum() if mask_self.any() else np.nan

        # 우리사주: nm 또는 relate에 "우리사주" 포함
        mask_esop = (
            grp["nm"].str.contains("우리사주", na=False)
            | grp["relate"].str.contains("우리사주", na=False)
        )
        esop_pct = grp.loc[mask_esop, "stock_rate_f"].sum() if mask_esop.any() else 0.0

        # 특수관계인: 본인도 우리사주도 아닌 나머지
        mask_related = ~mask_self & ~mask_esop
        related_pct = grp.loc[mask_related, "stock_rate_f"].sum() if mask_related.any() else 0.0

        results.append({
            "corp_code": corp_code,
            "corp_name": corp_name,
            "market": market,
            "year": year,
            "largest_pct": largest_pct,
            "related_pct": related_pct,
            "esop_pct": esop_pct,
        })

    return pd.DataFrame(results)


def _parse_count(val: object) -> float:
    """주식 수량 문자열(콤마·공백 포함) → float. 변환 불가 시 NaN."""
    if pd.isna(val):
        return np.nan
    s = str(val).strip().replace(",", "").replace(" ", "")
    if s in ("", "-"):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def _pick_total_shares(row: pd.Series) -> float:
    """stockTotqySttus 응답의 여러 필드 중 실제 '발행주식 총수'에 해당하는 값 선택.

    우선순위:
      1) istc_totqy (유통주식총수 = 발행누적 − 감소누적, 가장 정확한 '현재 발행주식')
      2) now_to_isu_stock_totqy − now_to_redc_stock_totqy (있으면)
      3) now_to_isu_stock_totqy (감소분 없을 때)
      4) isu_stock_totqy (정관상 한도이지만 최후의 폴백)
    """
    candidates = {
        "istc_totqy":              _parse_count(row.get("istc_totqy", "")),
        "now_to_isu":              _parse_count(row.get("now_to_isu_stock_totqy", "")),
        "now_to_redc":             _parse_count(row.get("now_to_redc_stock_totqy", "")),
        "isu_stock_totqy":         _parse_count(row.get("isu_stock_totqy", "")),
    }

    # 1순위: istc_totqy
    if not np.isnan(candidates["istc_totqy"]) and candidates["istc_totqy"] > 0:
        return candidates["istc_totqy"]

    # 2·3순위: 발행누적 − 감소누적
    if not np.isnan(candidates["now_to_isu"]) and candidates["now_to_isu"] > 0:
        redc = candidates["now_to_redc"] if not np.isnan(candidates["now_to_redc"]) else 0.0
        diff = candidates["now_to_isu"] - redc
        if diff > 0:
            return diff
        return candidates["now_to_isu"]

    # 4순위: isu_stock_totqy (폴백)
    if not np.isnan(candidates["isu_stock_totqy"]) and candidates["isu_stock_totqy"] > 0:
        return candidates["isu_stock_totqy"]

    return np.nan


def process_treasury(
    df_tres: pd.DataFrame,
    df_shares: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """treasury_raw.csv에서 자사주 비율 계산. 보통주(普通株)만 집계.

    비율 = trmend_qy(기말 자사주 수량) / 총발행주식수 * 100
    df_shares: total_shares_raw.csv 로드 결과 (없으면 NaN)
    """
    # 보통주만 필터 — 우선주 자사주는 의결권이 없으므로 제외
    df_tres = df_tres[df_tres["stock_knd"].str.contains("보통주", na=False)].copy()
    df_tres["trmend_qy_f"] = df_tres["trmend_qy"].apply(_parse_count)

    # 총발행주식수 조회용 딕셔너리: (corp_code, year) → total_shares
    shares_dict: dict[tuple[str, str], float] = {}
    if df_shares is not None and not df_shares.empty:
        # '발행한 주식의 총수' 구분 정확 일치 (부분일치는 '발행한 주식의 증감내역' 등을 오염시킬 수 있음)
        se_clean = df_shares["se"].fillna("").astype(str).str.strip()
        mask_issued = se_clean == "발행한 주식의 총수"
        if mask_issued.sum() == 0:
            # 폴백: 정확 일치 행이 없을 때 '주식의 총수' 포함 행 사용
            mask_issued = se_clean.str.contains("주식의 총수", na=False)

        df_issued = df_shares[mask_issued].copy()
        for _, row in df_issued.iterrows():
            key = (str(row["corp_code"]), str(row["year"]))
            val = _pick_total_shares(row)
            if not np.isnan(val) and val > 0:
                shares_dict[key] = val

    results = []
    for (corp_code, year), grp in df_tres.groupby(["corp_code", "year"]):
        trmend_qy = grp["trmend_qy_f"].sum()
        total_shares = shares_dict.get((str(corp_code), str(year)), np.nan)

        if np.isnan(total_shares) or total_shares <= 0:
            treasury_pct = np.nan
        else:
            treasury_pct = trmend_qy / total_shares * 100

        results.append({
            "corp_code": corp_code,
            "year": year,
            "treasury_pct": treasury_pct,
        })

    return pd.DataFrame(results)


def process_minority(df_min: pd.DataFrame) -> pd.DataFrame:
    """minority_raw.csv에서 소액주주 비율 추출."""
    df_min["hold_stock_rate_f"] = df_min["hold_stock_rate"].apply(parse_rate)

    results = []
    for (corp_code, year), grp in df_min.groupby(["corp_code", "year"]):
        # "소액주주" 행의 주식 보유 비율
        mask = grp["se"].str.contains("소액", na=False)
        minority_pct = grp.loc[mask, "hold_stock_rate_f"].iloc[0] if mask.any() else np.nan
        results.append({
            "corp_code": corp_code,
            "year": year,
            "minority_pct": minority_pct,
        })

    return pd.DataFrame(results)


def main() -> None:
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

    # 1. 최대주주 데이터 (필수)
    own_path = DATA_RAW / "ownership_raw.csv"
    if not own_path.exists():
        raise FileNotFoundError("ownership_raw.csv가 없습니다. 먼저 02_collect_ownership.py를 실행하세요.")

    logger.info("ownership_raw.csv 로드 중...")
    df_own = pd.read_csv(own_path, dtype=str)
    logger.info(f"  {len(df_own)}행 로드")
    df_panel = process_ownership(df_own)
    logger.info(f"  {len(df_panel)}개 기업-연도 조합 정제")

    # 2. 자사주 데이터 (선택)
    tres_path = DATA_RAW / "treasury_raw.csv"
    shares_path = DATA_RAW / "total_shares_raw.csv"
    if tres_path.exists():
        logger.info("treasury_raw.csv 로드 중...")
        df_tres = pd.read_csv(tres_path, dtype=str)

        df_shares = None
        if shares_path.exists():
            logger.info("total_shares_raw.csv 로드 중 (자사주 비율 계산용)...")
            df_shares = pd.read_csv(shares_path, dtype=str)
            logger.info(f"  {len(df_shares)}행 로드")
        else:
            logger.warning("total_shares_raw.csv 없음 → treasury_pct = NaN (03b 스크립트 실행 필요)")

        df_treasury = process_treasury(df_tres, df_shares)
        non_null = df_treasury["treasury_pct"].notna().sum()
        logger.info(f"  자사주 비율 계산: {non_null}/{len(df_treasury)}건 성공")
        df_panel = df_panel.merge(df_treasury, on=["corp_code", "year"], how="left")
        logger.info(f"  자사주 데이터 병합 완료")
    else:
        logger.warning("treasury_raw.csv 없음 → treasury_pct = NaN")
        df_panel["treasury_pct"] = np.nan

    # 3. 소액주주 데이터 (선택)
    min_path = DATA_RAW / "minority_raw.csv"
    if min_path.exists():
        logger.info("minority_raw.csv 로드 중...")
        df_min = pd.read_csv(min_path, dtype=str)
        df_minority = process_minority(df_min)
        df_panel = df_panel.merge(df_minority, on=["corp_code", "year"], how="left")
        logger.info(f"  소액주주 데이터 병합 완료")
    else:
        logger.warning("minority_raw.csv 없음 → minority_pct = NaN")
        df_panel["minority_pct"] = np.nan

    # 4. 우호지분 계산
    df_panel["treasury_pct"] = df_panel["treasury_pct"].fillna(0)
    df_panel["friendly_pct"] = (
        df_panel["largest_pct"]
        + df_panel["related_pct"]
        + df_panel["treasury_pct"]
        + df_panel["esop_pct"]
    )
    df_panel["voting_friendly_pct"] = df_panel["friendly_pct"] - df_panel["treasury_pct"]

    # 5. 저장
    out_path = DATA_PROCESSED / "ownership_panel.csv"
    df_panel.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info(f"저장: {out_path}")

    # 통계 요약
    logger.info("=== 패널 데이터 요약 ===")
    logger.info(f"  총 {len(df_panel)}개 기업-연도 관측치")
    logger.info(f"  연도 범위: {df_panel['year'].min()} ~ {df_panel['year'].max()}")
    for market in ["KOSPI", "KOSDAQ"]:
        cnt = len(df_panel[df_panel["market"] == market])
        logger.info(f"  {market}: {cnt}건")


if __name__ == "__main__":
    main()
