#!/usr/bin/env python3
"""H1 검증: 2014년 이후 상장사의 지분율 패턴 차이.

가설:
  2014년 자본시장법 개정 이후 상장한 기업은 이전 상장사 대비
  최대주주·우호지분 구조가 다를 것 (벤처·신산업 비중 ↑, 분산 소유 ↑).

추정 모델:
  largest_pct (또는 friendly_pct) = β0 + β1·post2014 + β2·X + ε
  with cluster-robust SE at corp_code

  post2014 = 1 if isu_dt(상장일) >= 2014-01-01 else 0

  X = leverage, size, roa, market FE, year FE

확장 모델:
  + 상호작용항: post2014 × year_int  (개혁 효과의 시간 추세)

입력:
  data/raw/listed_corps.csv                    — corp_code, isu_dt
  data/processed/ownership_panel.csv           — Step 5
  data/processed/ownership_financial_panel.csv — Step 10 (재무 통제 변수)

출력:
  data/output/h1_regression_results.csv  — 모델별 계수
  data/output/h1_post2014_summary.csv    — pre/post 그룹 평균 비교
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROCESSED = BASE_DIR / "data" / "processed"
DATA_OUTPUT = BASE_DIR / "data" / "output"

LISTED_PATH = DATA_RAW / "listed_corps.csv"
PANEL_PATH = DATA_PROCESSED / "ownership_panel.csv"
FIN_PANEL_PATH = DATA_PROCESSED / "ownership_financial_panel.csv"

CUTOFF_YEAR = 2014


def load_with_listing_dates() -> pd.DataFrame:
    """ownership(_financial)_panel + listed_corps(isu_dt) 병합."""
    if not LISTED_PATH.exists():
        raise FileNotFoundError(f"{LISTED_PATH} 없음 — Step 1b 먼저")

    listed = pd.read_csv(LISTED_PATH, dtype=str, encoding="utf-8-sig")
    listed.columns = [c.lstrip("﻿").strip() for c in listed.columns]
    if "isu_dt" not in listed.columns:
        raise ValueError(
            f"listed_corps.csv에 isu_dt 컬럼 없음 — Step 1b(01b_get_listing_dates.py) 미완료"
        )
    logger.info(f"listed_corps: {len(listed):,}행, isu_dt 비결측 {listed['isu_dt'].notna().sum():,}")

    # 재무 통제 변수가 있으면 그쪽 사용 (조인된 패널), 없으면 ownership_panel만 사용
    if FIN_PANEL_PATH.exists():
        df = pd.read_csv(FIN_PANEL_PATH, dtype={"corp_code": str, "year": str},
                          encoding="utf-8-sig")
        df.columns = [c.lstrip("﻿").strip() for c in df.columns]
        logger.info(f"ownership_financial_panel 사용: {len(df):,}행")
    elif PANEL_PATH.exists():
        df = pd.read_csv(PANEL_PATH, dtype={"corp_code": str, "year": str},
                          encoding="utf-8-sig")
        df.columns = [c.lstrip("﻿").strip() for c in df.columns]
        logger.warning("ownership_financial_panel 없음 — ownership_panel.csv만 사용 (재무 통제 변수 미사용)")
    else:
        raise FileNotFoundError("패널 데이터 없음 — Step 5/10 먼저")

    df = df.merge(listed[["corp_code", "isu_dt"]], on="corp_code", how="left")
    matched = df["isu_dt"].notna().sum()
    logger.info(f"isu_dt 매칭: {matched:,}/{len(df):,} ({matched / len(df) * 100:.1f}%)")
    return df


def build_post2014(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["isu_year"] = pd.to_datetime(df["isu_dt"], errors="coerce").dt.year
    df["post2014"] = (df["isu_year"] >= CUTOFF_YEAR).astype(int)
    df.loc[df["isu_year"].isna(), "post2014"] = np.nan
    df["year_int"] = df["year"].astype(int)
    return df


def filter_valid(df: pd.DataFrame, dv: str) -> pd.DataFrame:
    needed = [dv, "post2014"]
    if "leverage" in df.columns:
        needed += ["leverage", "size", "roa"]
    before = len(df)
    out = df.dropna(subset=needed).copy()
    logger.info(f"[{dv}] 결측 제거: {before:,} → {len(out):,}")
    return out


def run_ols(df: pd.DataFrame, formula: str, label: str) -> dict:
    import statsmodels.formula.api as smf

    model = smf.ols(formula, data=df).fit(
        cov_type="cluster", cov_kwds={"groups": df["corp_code"]}
    )

    rows = []
    for var in model.params.index:
        if var.startswith(("C(market)", "C(year_int)", "Intercept")):
            continue
        rows.append({
            "model": label,
            "variable": var,
            "coef": round(float(model.params[var]), 5),
            "se": round(float(model.bse[var]), 5),
            "t": round(float(model.tvalues[var]), 3),
            "p": round(float(model.pvalues[var]), 4),
        })

    summary = {
        "model": label,
        "n": int(model.nobs),
        "r2": round(float(model.rsquared), 4),
        "adj_r2": round(float(model.rsquared_adj), 4),
    }
    logger.info(f"\n=== {label} === N={summary['n']:,} | R²={summary['r2']}")
    for r in rows:
        sig = "***" if r["p"] < 0.01 else ("**" if r["p"] < 0.05 else ("*" if r["p"] < 0.1 else ""))
        logger.info(f"  {r['variable']:<25} {r['coef']:>10.4f} ({r['se']:.4f}) {sig}")
    return {"summary": summary, "coefs": rows}


def group_compare(df: pd.DataFrame) -> pd.DataFrame:
    """pre/post 2014 그룹별 평균 (largest, friendly, treasury, esop)."""
    out = []
    for label, sub in [("전체", df), ("KOSPI", df[df["market"] == "KOSPI"]),
                         ("KOSDAQ", df[df["market"] == "KOSDAQ"])]:
        if sub.empty:
            continue
        for grp_label, grp_val in [("pre2014", 0), ("post2014", 1)]:
            g = sub[sub["post2014"] == grp_val]
            if g.empty:
                continue
            row = {"market": label, "group": grp_label, "n": len(g)}
            for col in ["largest_pct", "friendly_pct", "treasury_pct", "esop_pct"]:
                if col in g.columns:
                    row[f"{col}_mean"] = round(float(g[col].mean()), 3)
            out.append(row)
    return pd.DataFrame(out)


def main() -> None:
    DATA_OUTPUT.mkdir(parents=True, exist_ok=True)

    df = load_with_listing_dates()
    df = build_post2014(df)

    n_post = (df["post2014"] == 1).sum()
    n_pre = (df["post2014"] == 0).sum()
    logger.info(f"post2014=1: {n_post:,}건 | post2014=0: {n_pre:,}건")

    has_financial = "leverage" in df.columns and df["leverage"].notna().any()

    all_results: list[dict] = []
    for dv in ["largest_pct", "friendly_pct"]:
        if dv not in df.columns:
            continue
        sub = filter_valid(df, dv)
        if len(sub) < 100:
            logger.warning(f"[{dv}] 관측치 부족 — 스킵")
            continue

        # M1: 단순 (시장 FE만)
        all_results.append(run_ols(sub,
            f"{dv} ~ post2014 + C(market)", f"{dv}::M1 단순+시장FE"))

        # M2: + 연도 FE
        all_results.append(run_ols(sub,
            f"{dv} ~ post2014 + C(market) + C(year_int)", f"{dv}::M2 +연도FE"))

        # M3: + 재무 통제 (가능시)
        if has_financial:
            all_results.append(run_ols(sub,
                f"{dv} ~ post2014 + leverage + size + roa + C(market) + C(year_int)",
                f"{dv}::M3 +재무통제"))

            # M4: + 상호작용 (post2014 × year_int)
            all_results.append(run_ols(sub,
                f"{dv} ~ post2014 * year_int + leverage + size + roa + C(market)",
                f"{dv}::M4 +시간추세 상호작용"))

    coefs_df = pd.DataFrame([c for r in all_results for c in r["coefs"]])
    sums_df = pd.DataFrame([r["summary"] for r in all_results])
    coefs_df.to_csv(DATA_OUTPUT / "h1_regression_results.csv", index=False, encoding="utf-8-sig")
    sums_df.to_csv(DATA_OUTPUT / "h1_regression_summary.csv", index=False, encoding="utf-8-sig")

    grp = group_compare(df)
    grp.to_csv(DATA_OUTPUT / "h1_post2014_summary.csv", index=False, encoding="utf-8-sig")
    logger.info(f"\n=== pre/post 2014 그룹 비교 ===\n{grp.to_string(index=False)}")
    logger.info(f"\n저장: {DATA_OUTPUT / 'h1_regression_results.csv'}")


if __name__ == "__main__":
    main()
