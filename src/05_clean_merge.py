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
    # DART API 응답의 소계 집계행 제거 ("계", "소계", "합계" 행은 개별 주주가 아닌 합산행)
    agg_mask = df_own["nm"].fillna("").str.strip().isin(["계", "소계", "합계"])
    if agg_mask.any():
        logger.info(f"  집계행 제거: {agg_mask.sum():,}행 (nm='계'/'소계'/'합계')")
    df_own = df_own[~agg_mask].copy()

    df_own["stock_rate_f"] = df_own["stock_rate"].apply(parse_rate)
    # relate 정규화 (strip) — 공백 포함/제거된 같은 값 통합
    df_own["relate_clean"] = df_own["relate"].fillna("").astype(str).str.strip()

    results = []
    for (corp_code, year), grp in df_own.groupby(["corp_code", "year"]):
        corp_name = grp["corp_name"].iloc[0]
        market = grp["market"].iloc[0]

        # 최대주주 본인 식별:
        #   (1) relate == "본인" / "최대주주" / "최대주주 본인" 정확일치
        #   (2) relate 에 "본인" 포함 (예: "본인(대표이사)")
        # DART 공시에서 기업마다 표기가 달라 OR 조합 사용.
        mask_self = (
            grp["relate_clean"].isin(["본인", "최대주주", "최대주주 본인"])
            | grp["relate_clean"].str.contains("본인", na=False)
        )
        largest_pct = grp.loc[mask_self, "stock_rate_f"].sum() if mask_self.any() else np.nan

        # 우리사주: nm 또는 relate에 "우리사주" 포함
        mask_esop = (
            grp["nm"].fillna("").str.contains("우리사주", na=False)
            | grp["relate_clean"].str.contains("우리사주", na=False)
        )
        esop_pct = grp.loc[mask_esop, "stock_rate_f"].sum() if mask_esop.any() else 0.0

        # 공익법인: relate에 "공익법인" 포함 (H3 합성 우호지분 지수용 — related_pct 내 서브컴포넌트)
        mask_foundation = grp["relate_clean"].str.contains("공익법인", na=False)
        foundation_pct = grp.loc[mask_foundation, "stock_rate_f"].sum() if mask_foundation.any() else 0.0

        # 특수관계인: 본인도 우리사주도 아닌 나머지 (공익법인 포함 — 현행 유지)
        mask_related = ~mask_self & ~mask_esop
        related_pct = grp.loc[mask_related, "stock_rate_f"].sum() if mask_related.any() else 0.0

        results.append({
            "corp_code": corp_code,
            "corp_name": corp_name,
            "market": market,
            "year": year,
            "largest_pct": largest_pct,
            "related_pct": related_pct,        # 공익법인 포함 (현행 유지)
            "esop_pct": esop_pct,
            "foundation_pct": foundation_pct,  # related_pct의 서브컴포넌트 (H3용)
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
    """stockTotqySttus 응답에서 '현재 발행주식 총수' 선택.

    우선순위:
      1) istc_totqy (유통주식총수 = 발행누적 − 감소누적, 가장 정확)
      2) now_to_isu_stock_totqy − now_to_redc_stock_totqy
      3) now_to_isu_stock_totqy (감소분 없을 때)

    주의: `isu_stock_totqy`는 정관상 '발행할 주식의 총수'(한도)이므로
    실제 발행주식수와 무관하여 폴백으로 사용 금지. 위 3개가 모두 비면 NaN.
    """
    istc = _parse_count(row.get("istc_totqy", ""))
    now_isu = _parse_count(row.get("now_to_isu_stock_totqy", ""))
    now_redc = _parse_count(row.get("now_to_redc_stock_totqy", ""))

    if not np.isnan(istc) and istc > 0:
        return istc

    if not np.isnan(now_isu) and now_isu > 0:
        redc = now_redc if not np.isnan(now_redc) else 0.0
        diff = now_isu - redc
        if diff > 0:
            return diff
        return now_isu

    return np.nan


def process_treasury(
    df_tres: pd.DataFrame,
    df_shares: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """treasury_raw.csv에서 자사주 비율 계산. 보통주(普通株)만 집계.

    1순위: DART가 직접 계산해 준 trmend_rate (공시 원문 비율) — 가장 신뢰성 높음.
    2순위: trmend_qy / total_shares × 100 — trmend_rate 없을 때만 사용.
           total_shares는 total_shares_raw.csv의 '합계' 행 기준.
    """
    df_tres = df_tres.copy()
    df_tres["stock_knd_clean"] = df_tres["stock_knd"].fillna("").astype(str).str.strip()
    logger.info(f"  자사주 stock_knd 고유값 상위: {df_tres['stock_knd_clean'].value_counts().head(10).to_dict()}")
    df_tres = df_tres[df_tres["stock_knd_clean"].str.contains("보통", na=False)].copy()
    logger.info(f"  보통주 필터 후: {len(df_tres):,}행")

    # DART 직접 계산 비율 파싱 (1순위)
    df_tres["trmend_rate_f"] = df_tres["trmend_rate"].apply(parse_rate) if "trmend_rate" in df_tres.columns else np.nan
    df_tres["trmend_qy_f"] = df_tres["trmend_qy"].apply(_parse_count)

    # total_shares 딕셔너리: '합계' 행 우선, 보통주 행 폴백 (2순위 계산용)
    shares_dict: dict[tuple[str, str], float] = {}
    if df_shares is not None and not df_shares.empty:
        se_clean = df_shares["se"].fillna("").astype(str).str.strip()
        # '합계' 행 = 전체 주식종류 합산 → 분모로 가장 안전
        for _, row in df_shares[se_clean == "합계"].iterrows():
            key = (str(row["corp_code"]), str(row["year"]))
            val = _pick_total_shares(row)
            if not np.isnan(val) and val > 0 and key not in shares_dict:
                shares_dict[key] = val
        # '보통주' 행 폴백 (합계 없는 기업)
        for _, row in df_shares[se_clean.str.contains("보통", na=False)].iterrows():
            key = (str(row["corp_code"]), str(row["year"]))
            if key not in shares_dict:
                val = _pick_total_shares(row)
                if not np.isnan(val) and val > 0:
                    shares_dict[key] = val
        logger.info(f"  총발행주식수 shares_dict: {len(shares_dict):,}건 구축")

    results = []
    rate_used, calc_used, nan_used, capped = 0, 0, 0, 0
    for (corp_code, year), grp in df_tres.groupby(["corp_code", "year"]):
        # 1순위: DART trmend_rate (이미 퍼센트 단위, 0~100 범위만 수용)
        valid_rate = grp["trmend_rate_f"].dropna()
        valid_rate = valid_rate[(valid_rate >= 0) & (valid_rate <= 100)]
        if not valid_rate.empty:
            treasury_pct = valid_rate.iloc[0]
            rate_used += 1
        else:
            # 2순위: 수량 / 총발행주식수
            trmend_qy = grp["trmend_qy_f"].sum()
            total_shares = shares_dict.get((str(corp_code), str(year)), np.nan)
            if not np.isnan(total_shares) and total_shares > 0 and not np.isnan(trmend_qy):
                raw_pct = trmend_qy / total_shares * 100
                # 100% 초과 = 보고 단위 불일치 등 데이터 오류 → NaN 처리
                if raw_pct > 100:
                    treasury_pct = np.nan
                    capped += 1
                else:
                    treasury_pct = raw_pct
                    calc_used += 1
            else:
                treasury_pct = np.nan
                nan_used += 1

        results.append({
            "corp_code": corp_code,
            "year": year,
            "treasury_pct": treasury_pct,
        })

    logger.info(
        f"  자사주 비율: trmend_rate {rate_used:,}건 | 수량계산 {calc_used:,}건 | "
        f"단위오류(>100%) {capped:,}건 | NaN {nan_used:,}건"
    )
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
            if not df_shares.empty and "se" in df_shares.columns:
                logger.info(f"  se 고유값 상위 10: {df_shares['se'].value_counts().head(10).to_dict()}")
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
    df_panel["foundation_pct"] = df_panel["foundation_pct"].fillna(0)

    # friendly_pct (현행): largest + related(공익법인 포함) + esop + treasury
    # → KCMI 24-20 정의와 동일 (비교 가능), related_pct 내 공익법인 이중 계산 없음
    df_panel["friendly_pct"] = (
        df_panel["largest_pct"]
        + df_panel["related_pct"]
        + df_panel["treasury_pct"]
        + df_panel["esop_pct"]
    )
    df_panel["voting_friendly_pct"] = df_panel["friendly_pct"] - df_panel["treasury_pct"]

    # KCMI 벤치마크 비교 컬럼 (2023년말 기준 고정값)
    KCMI_BENCHMARK = {"전체": 43.07, "KOSPI": 49.34, "KOSDAQ": 39.93}
    df_panel["kcmi_friendly_benchmark"] = df_panel["market"].map(KCMI_BENCHMARK)

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
