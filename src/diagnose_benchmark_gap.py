#!/usr/bin/env python3
"""KCMI 24-20 벤치마크 격차 원인 진단.

문제: 2023년 friendly_pct_mean이 KCMI 보고서 대비 -2.5 ~ -4.2%p 낮음.
  - 전체   40.14% vs 43.07% (-2.93%p)
  - KOSPI  45.14% vs 49.34% (-4.20%p)  ← 격차 가장 큼
  - KOSDAQ 37.40% vs 39.93% (-2.53%p)

가설:
  H-A) 모집단 차이: 12월 결산법인만 분석? SPAC·금융업 제외? 코넥스 포함?
  H-B) 가중방식 차이: KCMI는 시가총액 가중평균? (대형주 = 재벌 = 높은 우호지분)
  H-C) 결측 처리 차이: largest_pct NaN 기업이 평균에서 빠져 편향?
  H-D) 변수 정의: friendly_pct에 우리사주 포함 여부, 자사주 처리

실행: 직접 raw/processed 데이터 위에서 시나리오별 평균을 다시 계산해 보고,
어떤 필터·가중을 적용했을 때 KCMI 수치에 가장 가까워지는지 확인한다.

입력:
  data/processed/ownership_panel.csv  (필수, Step 5 산출)
  data/raw/corp_details.csv           (선택, Step 1c — 결산월 · 업종)
  data/raw/market_cap_raw.csv         (선택, Step 9 — 가중평균용)
  data/raw/listed_corps.csv           (선택, Step 1 — corp_name)

출력:
  diagnostics/benchmark_gap_2023.csv  (시나리오별 평균/중앙값/N)
  diagnostics/benchmark_gap_summary.md (사람이 읽는 요약 보고서)
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
DIAG_DIR = BASE_DIR / "diagnostics"

KCMI_2023 = {
    ("전체", "largest_pct"): 29.21,
    ("전체", "friendly_pct"): 43.07,
    ("KOSPI", "friendly_pct"): 49.34,
    ("KOSDAQ", "friendly_pct"): 39.93,
}


def load_panel() -> pd.DataFrame:
    path = DATA_PROCESSED / "ownership_panel.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} 없음 — Step 5(05_clean_merge.py) 먼저 실행")
    df = pd.read_csv(path, dtype={"corp_code": str, "year": str})
    return df[df["year"] == "2023"].copy()


def attach_corp_details(df: pd.DataFrame) -> pd.DataFrame:
    path = DATA_RAW / "corp_details.csv"
    if not path.exists():
        logger.warning(f"{path} 없음 — Step 1c 미완료, 결산월/업종 시나리오 스킵")
        df["acc_mt"] = np.nan
        df["induty_code"] = np.nan
        return df
    cd = pd.read_csv(path, dtype=str)
    keep = [c for c in ["corp_code", "acc_mt", "induty_code", "est_dt"] if c in cd.columns]
    return df.merge(cd[keep], on="corp_code", how="left")


def attach_market_cap(df: pd.DataFrame) -> pd.DataFrame:
    path = DATA_RAW / "market_cap_raw.csv"
    if not path.exists():
        logger.warning(f"{path} 없음 — Step 9 미완료, 가중평균 시나리오 스킵")
        df["market_cap"] = np.nan
        return df
    mc = pd.read_csv(path, dtype=str)
    mc["year"] = mc["year"].astype(str)
    mc = mc[mc["year"] == "2023"].copy()
    mc["market_cap_f"] = (
        mc["market_cap"].astype(str).str.replace(",", "").str.strip().replace({"": np.nan, "-": np.nan})
    )
    mc["market_cap_f"] = pd.to_numeric(mc["market_cap_f"], errors="coerce")
    mc = mc.sort_values("market_cap_f", ascending=False).drop_duplicates("corp_code", keep="first")
    return df.merge(mc[["corp_code", "market_cap_f"]], on="corp_code", how="left")


def weighted_mean(s: pd.Series, w: pd.Series) -> float:
    mask = s.notna() & w.notna() & (w > 0)
    if not mask.any():
        return np.nan
    return float((s[mask] * w[mask]).sum() / w[mask].sum())


def scenario_stats(df: pd.DataFrame, label: str, weight_col: str | None = None) -> list[dict]:
    rows = []
    for market_label, sub in [("전체", df), ("KOSPI", df[df["market"] == "KOSPI"]),
                                 ("KOSDAQ", df[df["market"] == "KOSDAQ"])]:
        if sub.empty:
            continue
        for col in ["largest_pct", "friendly_pct"]:
            valid = sub[col].notna().sum()
            if weight_col is not None:
                mean_v = weighted_mean(sub[col], sub[weight_col])
            else:
                mean_v = sub[col].mean()
            kcmi = KCMI_2023.get((market_label, col))
            rows.append({
                "scenario": label,
                "market": market_label,
                "metric": col,
                "n": int(valid),
                "mean": round(float(mean_v), 4) if pd.notna(mean_v) else None,
                "median": round(float(sub[col].median()), 4) if valid else None,
                "kcmi": kcmi,
                "diff_kcmi": round(float(mean_v) - kcmi, 4) if (pd.notna(mean_v) and kcmi is not None) else None,
            })
    return rows


def diagnose_field_completeness(df: pd.DataFrame) -> dict[str, int]:
    """largest_pct/treasury_pct/esop_pct/foundation_pct 결측·0 비율."""
    info = {
        "n_total": len(df),
        "largest_pct_nan": int(df["largest_pct"].isna().sum()),
        "largest_pct_zero": int((df["largest_pct"] == 0).sum()),
        "treasury_pct_zero": int((df["treasury_pct"].fillna(0) == 0).sum()),
        "esop_pct_zero": int((df["esop_pct"].fillna(0) == 0).sum()),
        "foundation_pct_nonzero": int((df["foundation_pct"].fillna(0) > 0).sum()),
        "friendly_pct_nan": int(df["friendly_pct"].isna().sum()),
    }
    return info


def main() -> None:
    DIAG_DIR.mkdir(parents=True, exist_ok=True)

    df = load_panel()
    logger.info(f"2023년 ownership_panel: {len(df):,}행")

    df = attach_corp_details(df)
    df = attach_market_cap(df)

    completeness = diagnose_field_completeness(df)
    logger.info("\n=== 필드 완결성 (2023) ===")
    for k, v in completeness.items():
        logger.info(f"  {k}: {v:,}")

    all_rows: list[dict] = []

    # A) 현행 (모든 결산월, 단순평균) — yearly_stats와 동일해야 함
    all_rows += scenario_stats(df, "A: 현행 (단순평균)")

    # B) 12월 결산 기업만 (acc_mt == "12")
    if df["acc_mt"].notna().any():
        df_dec = df[df["acc_mt"].astype(str) == "12"].copy()
        all_rows += scenario_stats(df_dec, "B: 12월 결산만")
        logger.info(f"B: 12월 결산 기업 N = {len(df_dec):,}")
    else:
        logger.warning("B 스킵 — corp_details.csv 미존재")

    # C) 시가총액 가중평균 (현행 모집단)
    if df["market_cap_f"].notna().any():
        all_rows += scenario_stats(df, "C: 시가총액 가중평균", weight_col="market_cap_f")
    else:
        logger.warning("C 스킵 — market_cap_raw.csv 미존재")

    # D) largest_pct 결측 제외 (현행과 동일 — pandas mean이 NaN 무시)
    df_lg = df[df["largest_pct"].notna()].copy()
    all_rows += scenario_stats(df_lg, "D: largest_pct 결측 제외만")

    # E) SPAC + 금융업 제외 (corp_name + induty_code)
    name_excl = df["corp_name"].fillna("").str.contains("스팩|기업인수목적", na=False)
    if df["induty_code"].notna().any():
        # K64 = 금융업 (KSIC 분류), 모든 64xxx 코드
        induty_str = df["induty_code"].astype(str)
        fin_mask = induty_str.str.startswith("64") | induty_str.str.startswith("65") | induty_str.str.startswith("66")
        excl = name_excl | fin_mask
    else:
        excl = name_excl
    df_excl = df[~excl].copy()
    logger.info(f"E: 제외 대상 {int(excl.sum()):,}개사 (SPAC: {int(name_excl.sum())}, 금융: {int(excl.sum() - name_excl.sum())})")
    all_rows += scenario_stats(df_excl, "E: SPAC·금융 제외")

    # F) 시총 상위 80% (KCMI가 작은 기업을 포함하지 않았을 가능성 점검)
    if df["market_cap_f"].notna().any():
        top80_kospi = df[df["market"] == "KOSPI"].nlargest(int(len(df[df['market']=='KOSPI']) * 0.8), "market_cap_f")
        top80_kosdaq = df[df["market"] == "KOSDAQ"].nlargest(int(len(df[df['market']=='KOSDAQ']) * 0.8), "market_cap_f")
        df_top = pd.concat([top80_kospi, top80_kosdaq])
        all_rows += scenario_stats(df_top, "F: 시총 상위 80%")

    # G) B + E 복합 (12월 결산 + SPAC·금융 제외)
    if df["acc_mt"].notna().any():
        df_be = df[(df["acc_mt"].astype(str) == "12") & (~excl)].copy()
        all_rows += scenario_stats(df_be, "G: 12월결산 + SPAC·금융 제외")

    # H) 12월 결산 + 시가총액 가중평균
    if df["acc_mt"].notna().any() and df["market_cap_f"].notna().any():
        df_b = df[df["acc_mt"].astype(str) == "12"].copy()
        all_rows += scenario_stats(df_b, "H: 12월결산 + 시총 가중평균", weight_col="market_cap_f")

    out_csv = DIAG_DIR / "benchmark_gap_2023.csv"
    out_df = pd.DataFrame(all_rows)
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    logger.info(f"\n저장: {out_csv}")

    # 콘솔 요약
    logger.info("\n=== 시나리오별 friendly_pct mean (2023) ===")
    pivot = out_df[out_df["metric"] == "friendly_pct"].pivot_table(
        index="scenario", columns="market", values="mean"
    )
    logger.info(f"\n{pivot.to_string()}")

    logger.info("\n=== 시나리오별 KCMI 격차 (friendly_pct, %p) ===")
    pivot_diff = out_df[out_df["metric"] == "friendly_pct"].pivot_table(
        index="scenario", columns="market", values="diff_kcmi"
    )
    logger.info(f"\n{pivot_diff.to_string()}")

    # 마크다운 보고서 작성
    md_path = DIAG_DIR / "benchmark_gap_summary.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# KCMI 24-20 벤치마크 격차 진단 (2023년)\n\n")
        f.write("## 필드 완결성\n\n")
        for k, v in completeness.items():
            f.write(f"- **{k}**: {v:,}\n")
        f.write("\n## 시나리오별 friendly_pct_mean\n\n")
        f.write(pivot.round(2).to_markdown())
        f.write("\n\n## 시나리오별 KCMI 격차 (%p)\n\n")
        f.write(pivot_diff.round(2).to_markdown())
        f.write("\n\n## KCMI 벤치마크 (참조)\n\n")
        for (m, c), v in KCMI_2023.items():
            f.write(f"- {m} {c}: **{v}%**\n")
    logger.info(f"저장: {md_path}")


if __name__ == "__main__":
    main()
