#!/usr/bin/env python3
"""H3 검증: 우호지분율 ↑ → Tobin Q ↑ (소유구조와 기업가치).

가설:
  우호지분(largest + related + esop + treasury)이 높을수록 기업가치가 어떻게 변하나?
  - 양(+): 안정적 지배구조 → 장기 투자·신뢰성 ↑
  - 음(-): 경영진 참호 효과(entrenchment) → 소수주주 권익 침해
  - U자형: 중간 구간이 최저 (지배 무력 + 경영진 견제 부재)

추정 모델:
  tobin_q = β0 + β1·friendly_pct + β2·X + 시장FE + 연도FE + ε
  with cluster-robust SE at corp_code

비선형 점검:
  tobin_q = ... + β1·friendly_pct + β2·friendly_pct² + ...

입력:
  data/processed/ownership_financial_panel.csv  — Step 10 산출
  (corp_code, year, market, friendly_pct, largest_pct, treasury_pct,
   tobin_q, leverage, size, roa, roe, market_to_book)

출력:
  data/output/h3_regression_results.csv  — 모델별 계수·SE·R²·N
  data/output/h3_friendly_quintile.csv   — 우호지분 5분위별 평균 Tobin Q
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PROCESSED = BASE_DIR / "data" / "processed"
DATA_OUTPUT = BASE_DIR / "data" / "output"

PANEL_PATH = DATA_PROCESSED / "ownership_financial_panel.csv"


def load_panel() -> pd.DataFrame:
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"{PANEL_PATH} 없음 — Step 10(10_compute_tobin_q.py) 먼저 실행")
    df = pd.read_csv(PANEL_PATH, dtype={"corp_code": str, "year": str}, encoding="utf-8-sig")
    df.columns = [c.lstrip("﻿").strip() for c in df.columns]
    logger.info(f"패널 로드: {len(df):,}행 | 컬럼 {len(df.columns)}개")
    return df


def filter_valid(df: pd.DataFrame) -> pd.DataFrame:
    """결측·극단값 제거. 윈저화는 Step 10에서 수행했으므로 NaN 제거만."""
    needed = ["tobin_q", "friendly_pct", "leverage", "size", "roa"]
    before = len(df)
    df = df.dropna(subset=needed).copy()
    logger.info(f"필수변수 결측 제거: {before:,} → {len(df):,}")

    # tobin_q 0 또는 음수 제외 (이론적 하한)
    df = df[df["tobin_q"] > 0].copy()
    df["friendly_pct"] = df["friendly_pct"].astype(float)
    df["friendly_pct_sq"] = df["friendly_pct"] ** 2 / 100.0  # 스케일 정규화
    df["year_int"] = df["year"].astype(int)
    return df


def run_ols(df: pd.DataFrame, formula: str, label: str) -> dict:
    """statsmodels OLS + cluster-robust SE (corp_code 기준)."""
    import statsmodels.formula.api as smf

    model = smf.ols(formula, data=df).fit(
        cov_type="cluster", cov_kwds={"groups": df["corp_code"]}
    )

    # 주요 계수만 추출
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
        "f_stat": round(float(model.fvalue), 2) if model.fvalue is not None else None,
    }
    logger.info(f"\n=== {label} ===")
    logger.info(f"N={summary['n']:,} | R²={summary['r2']} | adj.R²={summary['adj_r2']}")
    for r in rows:
        sig = "***" if r["p"] < 0.01 else ("**" if r["p"] < 0.05 else ("*" if r["p"] < 0.1 else ""))
        logger.info(f"  {r['variable']:<25} {r['coef']:>10.4f} ({r['se']:.4f}) {sig}")
    return {"summary": summary, "coefs": rows}


def quintile_summary(df: pd.DataFrame) -> pd.DataFrame:
    """우호지분 5분위별 평균 Tobin Q + 시장별."""
    df = df.copy()
    df["friendly_quintile"] = pd.qcut(df["friendly_pct"], q=5, labels=[1, 2, 3, 4, 5])
    out = []
    for label, sub in [("전체", df), ("KOSPI", df[df["market"] == "KOSPI"]),
                         ("KOSDAQ", df[df["market"] == "KOSDAQ"])]:
        if sub.empty:
            continue
        for q in [1, 2, 3, 4, 5]:
            qsub = sub[sub["friendly_quintile"] == q]
            out.append({
                "market": label,
                "quintile": int(q),
                "n": len(qsub),
                "friendly_pct_mean": round(qsub["friendly_pct"].mean(), 2),
                "tobin_q_mean": round(qsub["tobin_q"].mean(), 4),
                "tobin_q_median": round(qsub["tobin_q"].median(), 4),
                "leverage_mean": round(qsub["leverage"].mean(), 4),
                "roa_mean": round(qsub["roa"].mean(), 4),
            })
    return pd.DataFrame(out)


def main() -> None:
    DATA_OUTPUT.mkdir(parents=True, exist_ok=True)

    df = load_panel()
    df = filter_valid(df)

    if len(df) < 100:
        logger.error(f"분석 불가 — 유효 관측치 부족 ({len(df)})")
        return

    results: list[dict] = []

    # M1: 단순 — friendly_pct만
    results.append(run_ols(df,
        "tobin_q ~ friendly_pct", "M1: 단순"))

    # M2: + 통제변수
    results.append(run_ols(df,
        "tobin_q ~ friendly_pct + leverage + size + roa", "M2: + 통제변수"))

    # M3: + 시장FE + 연도FE
    results.append(run_ols(df,
        "tobin_q ~ friendly_pct + leverage + size + roa + C(market) + C(year_int)",
        "M3: + 시장·연도 FE"))

    # M4: 비선형 (제곱항)
    results.append(run_ols(df,
        "tobin_q ~ friendly_pct + friendly_pct_sq + leverage + size + roa + C(market) + C(year_int)",
        "M4: + 비선형(²)"))

    # M5: largest + treasury 분리
    results.append(run_ols(df,
        "tobin_q ~ largest_pct + treasury_pct + leverage + size + roa + C(market) + C(year_int)",
        "M5: largest + treasury 분리"))

    # 결과 저장
    coefs_df = pd.DataFrame([c for r in results for c in r["coefs"]])
    sums_df = pd.DataFrame([r["summary"] for r in results])
    out_path = DATA_OUTPUT / "h3_regression_results.csv"
    coefs_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    sums_df.to_csv(DATA_OUTPUT / "h3_regression_summary.csv", index=False, encoding="utf-8-sig")
    logger.info(f"\n저장: {out_path}")

    # 5분위별 요약
    q_df = quintile_summary(df)
    q_path = DATA_OUTPUT / "h3_friendly_quintile.csv"
    q_df.to_csv(q_path, index=False, encoding="utf-8-sig")
    logger.info(f"저장: {q_path}")
    logger.info(f"\n=== 우호지분 5분위별 Tobin Q ===\n{q_df.to_string(index=False)}")


if __name__ == "__main__":
    main()
