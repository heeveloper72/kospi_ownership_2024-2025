#!/usr/bin/env python3
"""H5 검증: 재벌 소속 × 지배구조 개혁 (자본시장 규제 강화 효과의 이질성).

가설:
  자본시장법 개정·자사주 규제 등 지배구조 개혁의 효과가 재벌과 비재벌에서 다르게 나타남.
  - 재벌은 그룹 내 순환출자·계열사 동원으로 지배력 유지 → 개혁 효과 둔화
  - 비재벌은 직접 영향 → 친밀우호 비율 변화 더 큼

추정 모델 (Difference-in-Differences):
  friendly_pct = β0 + β1·chaebol + β2·post_reform + β3·chaebol×post_reform + X + ε

이벤트 시점:
  - 2017: 자사주 보유 보고 강화 + 스튜어드십 코드 도입
  - 2024: 자사주 소각 의무화 (구체 시점은 2024 시행)

입력:
  data/raw/chaebol_list.csv                    — 재벌 명단 (corp_name_pattern)
  data/raw/listed_corps.csv                    — corp_code ↔ corp_name 매칭
  data/processed/ownership_panel.csv           — Step 5
  data/processed/ownership_financial_panel.csv — Step 10 (재무 통제, 선택)

출력:
  data/output/h5_chaebol_classification.csv    — corp_code별 재벌 소속 매핑
  data/output/h5_did_results.csv               — DiD 회귀 결과
  data/output/h5_chaebol_summary.csv           — 재벌/비재벌 평균 비교
"""

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"
DATA_REFERENCE = BASE_DIR / "data" / "reference"
DATA_PROCESSED = BASE_DIR / "data" / "processed"
DATA_OUTPUT = BASE_DIR / "data" / "output"

CHAEBOL_PATH = DATA_REFERENCE / "chaebol_list.csv"
LISTED_PATH = DATA_RAW / "listed_corps.csv"
PANEL_PATH = DATA_PROCESSED / "ownership_panel.csv"
FIN_PANEL_PATH = DATA_PROCESSED / "ownership_financial_panel.csv"

REFORM_YEAR = 2017  # 1차 이벤트: 스튜어드십 코드 도입
REFORM_YEAR_2 = 2024  # 2차 이벤트: 자사주 소각 의무화


def classify_chaebol() -> pd.DataFrame:
    """corp_name → 재벌 매핑. 패턴 매칭 후 corp_code 단위로 chaebol_name 부여."""
    if not CHAEBOL_PATH.exists():
        raise FileNotFoundError(f"{CHAEBOL_PATH} 없음")
    if not LISTED_PATH.exists():
        raise FileNotFoundError(f"{LISTED_PATH} 없음")

    chaebol = pd.read_csv(CHAEBOL_PATH, encoding="utf-8-sig")
    chaebol.columns = [c.lstrip("﻿").strip() for c in chaebol.columns]
    listed = pd.read_csv(LISTED_PATH, dtype=str, encoding="utf-8-sig")
    listed.columns = [c.lstrip("﻿").strip() for c in listed.columns]
    logger.info(f"재벌 명단: {len(chaebol)}그룹 | 상장사: {len(listed):,}개")

    classifications = []
    for _, row in listed.iterrows():
        name = str(row.get("corp_name", "")).strip()
        matched = None
        for _, c in chaebol.iterrows():
            patterns = str(c["corp_name_pattern"]).split("|")
            for pat in patterns:
                pat = pat.strip()
                if not pat:
                    continue
                # negative lookahead 등 정규식 그대로 사용
                try:
                    if re.search(pat, name):
                        matched = c["chaebol_name"]
                        break
                except re.error:
                    if pat in name:
                        matched = c["chaebol_name"]
                        break
            if matched:
                break
        classifications.append({
            "corp_code": row["corp_code"],
            "corp_name": name,
            "chaebol_name": matched,
            "is_chaebol": int(matched is not None),
        })

    cls = pd.DataFrame(classifications)
    n_chaebol = cls["is_chaebol"].sum()
    logger.info(f"재벌 소속 분류: {n_chaebol:,}개사 / 비재벌 {len(cls) - n_chaebol:,}개사")
    return cls


def load_panel(cls: pd.DataFrame) -> pd.DataFrame:
    if FIN_PANEL_PATH.exists():
        df = pd.read_csv(FIN_PANEL_PATH, dtype={"corp_code": str, "year": str},
                          encoding="utf-8-sig")
        df.columns = [c.lstrip("﻿").strip() for c in df.columns]
        logger.info(f"ownership_financial_panel: {len(df):,}행")
    elif PANEL_PATH.exists():
        df = pd.read_csv(PANEL_PATH, dtype={"corp_code": str, "year": str},
                          encoding="utf-8-sig")
        df.columns = [c.lstrip("﻿").strip() for c in df.columns]
        logger.warning("ownership_financial_panel 없음 — ownership_panel.csv만 사용")
    else:
        raise FileNotFoundError("패널 데이터 없음")

    df = df.merge(cls[["corp_code", "chaebol_name", "is_chaebol"]], on="corp_code", how="left")
    df["is_chaebol"] = df["is_chaebol"].fillna(0).astype(int)
    df["year_int"] = df["year"].astype(int)
    df["post_reform"] = (df["year_int"] >= REFORM_YEAR).astype(int)
    df["post_reform_2"] = (df["year_int"] >= REFORM_YEAR_2).astype(int)
    return df


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
        logger.info(f"  {r['variable']:<35} {r['coef']:>10.4f} ({r['se']:.4f}) {sig}")
    return {"summary": summary, "coefs": rows}


def chaebol_summary(df: pd.DataFrame) -> pd.DataFrame:
    """재벌/비재벌 × 연도별 평균 친밀우호 비율."""
    out = []
    for label, sub in [("전체", df), ("KOSPI", df[df["market"] == "KOSPI"]),
                         ("KOSDAQ", df[df["market"] == "KOSDAQ"])]:
        if sub.empty:
            continue
        for is_c, gname in [(0, "비재벌"), (1, "재벌")]:
            g = sub[sub["is_chaebol"] == is_c]
            if g.empty:
                continue
            for col in ["largest_pct", "friendly_pct", "treasury_pct"]:
                if col in g.columns:
                    out.append({
                        "market": label, "group": gname, "metric": col,
                        "n": int(g[col].notna().sum()),
                        "mean": round(float(g[col].mean()), 3),
                        "median": round(float(g[col].median()), 3),
                    })
    return pd.DataFrame(out)


def main() -> None:
    DATA_OUTPUT.mkdir(parents=True, exist_ok=True)

    cls = classify_chaebol()
    cls.to_csv(DATA_OUTPUT / "h5_chaebol_classification.csv", index=False, encoding="utf-8-sig")
    logger.info(f"저장: h5_chaebol_classification.csv")

    df = load_panel(cls)

    # 재벌 분포
    chaebol_corps = df.loc[df["is_chaebol"] == 1, "corp_code"].nunique()
    nonchaebol_corps = df.loc[df["is_chaebol"] == 0, "corp_code"].nunique()
    logger.info(f"재벌 기업 {chaebol_corps:,}개 | 비재벌 {nonchaebol_corps:,}개")

    has_financial = "leverage" in df.columns and df["leverage"].notna().any()

    all_results: list[dict] = []
    for dv in ["friendly_pct", "largest_pct", "treasury_pct"]:
        if dv not in df.columns:
            continue
        sub = df.dropna(subset=[dv]).copy()
        if has_financial:
            sub = sub.dropna(subset=["leverage", "size", "roa"])
        if len(sub) < 100:
            continue

        # M1: DiD (1차 개혁 2017) — chaebol × post_reform
        f1 = f"{dv} ~ is_chaebol * post_reform + C(market)"
        all_results.append(run_ols(sub, f1, f"{dv}::DiD 2017 단순"))

        # M2: + 재무 통제 + 연도 FE
        if has_financial:
            f2 = f"{dv} ~ is_chaebol * post_reform + leverage + size + roa + C(market) + C(year_int)"
            all_results.append(run_ols(sub, f2, f"{dv}::DiD 2017 +통제"))

        # M3: 2차 개혁 (자사주 소각 의무화 2024)
        f3 = f"{dv} ~ is_chaebol * post_reform_2 + C(market) + C(year_int)"
        all_results.append(run_ols(sub, f3, f"{dv}::DiD 2024"))

    coefs_df = pd.DataFrame([c for r in all_results for c in r["coefs"]])
    sums_df = pd.DataFrame([r["summary"] for r in all_results])
    coefs_df.to_csv(DATA_OUTPUT / "h5_did_results.csv", index=False, encoding="utf-8-sig")
    sums_df.to_csv(DATA_OUTPUT / "h5_did_summary.csv", index=False, encoding="utf-8-sig")

    grp = chaebol_summary(df)
    grp.to_csv(DATA_OUTPUT / "h5_chaebol_summary.csv", index=False, encoding="utf-8-sig")
    logger.info(f"\n=== 재벌/비재벌 비교 ===\n{grp.to_string(index=False)}")
    logger.info(f"\n저장 완료")


if __name__ == "__main__":
    main()
