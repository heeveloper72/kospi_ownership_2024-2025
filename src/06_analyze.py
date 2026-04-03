#!/usr/bin/env python3
"""소유구조 패널 데이터의 통계 분석 및 벤치마크 비교."""

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
DATA_PROCESSED = BASE_DIR / "data" / "processed"
DATA_OUTPUT = BASE_DIR / "data" / "output"

# 자본시장연구원 벤치마크 (2023년말)
BENCHMARK = {
    "total": {"largest_pct": 29.21, "friendly_pct": 43.07},
    "KOSPI": {"friendly_pct": 49.34},
    "KOSDAQ": {"friendly_pct": 39.93},
}


def compute_yearly_stats(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """연도별 통계 계산."""
    stats = []
    for year, grp in df.groupby("year"):
        row = {"year": year, "market": label, "n": len(grp)}

        for col in ["largest_pct", "friendly_pct", "voting_friendly_pct"]:
            vals = grp[col].dropna()
            if len(vals) > 0:
                row[f"{col}_mean"] = vals.mean()
                row[f"{col}_median"] = vals.median()
                row[f"{col}_q1"] = vals.quantile(0.25)
                row[f"{col}_q3"] = vals.quantile(0.75)
                row[f"{col}_std"] = vals.std()
            else:
                for suffix in ["mean", "median", "q1", "q3", "std"]:
                    row[f"{col}_{suffix}"] = np.nan

        # 과반 미달 비율
        valid_largest = grp["largest_pct"].dropna()
        if len(valid_largest) > 0:
            row["pct_below50_largest"] = (valid_largest < 50).mean() * 100
        else:
            row["pct_below50_largest"] = np.nan

        valid_friendly = grp["friendly_pct"].dropna()
        if len(valid_friendly) > 0:
            row["pct_below50_friendly"] = (valid_friendly < 50).mean() * 100
        else:
            row["pct_below50_friendly"] = np.nan

        stats.append(row)

    return pd.DataFrame(stats)


def compare_benchmark(df: pd.DataFrame) -> None:
    """2023년 수치를 벤치마크와 비교 출력."""
    logger.info("\n=== 2023년 벤치마크 비교 ===")

    df_2023 = df[df["year"] == "2023"] if df["year"].dtype == object else df[df["year"] == 2023]

    if df_2023.empty:
        logger.warning("2023년 데이터 없음")
        return

    # 전체
    largest_mean = df_2023["largest_pct"].mean()
    friendly_mean = df_2023["friendly_pct"].mean()
    bm = BENCHMARK["total"]
    logger.info(f"[전체] 최대주주: {largest_mean:.2f}% (벤치마크: {bm['largest_pct']}%, 차이: {largest_mean - bm['largest_pct']:+.2f}%p)")
    logger.info(f"[전체] 우호지분: {friendly_mean:.2f}% (벤치마크: {bm['friendly_pct']}%, 차이: {friendly_mean - bm['friendly_pct']:+.2f}%p)")

    # KOSPI
    kospi = df_2023[df_2023["market"] == "KOSPI"]
    if not kospi.empty:
        friendly_kospi = kospi["friendly_pct"].mean()
        bm_k = BENCHMARK["KOSPI"]["friendly_pct"]
        logger.info(f"[KOSPI] 우호지분: {friendly_kospi:.2f}% (벤치마크: {bm_k}%, 차이: {friendly_kospi - bm_k:+.2f}%p)")

    # KOSDAQ
    kosdaq = df_2023[df_2023["market"] == "KOSDAQ"]
    if not kosdaq.empty:
        friendly_kosdaq = kosdaq["friendly_pct"].mean()
        bm_kd = BENCHMARK["KOSDAQ"]["friendly_pct"]
        logger.info(f"[KOSDAQ] 우호지분: {friendly_kosdaq:.2f}% (벤치마크: {bm_kd}%, 차이: {friendly_kosdaq - bm_kd:+.2f}%p)")


def main() -> None:
    DATA_OUTPUT.mkdir(parents=True, exist_ok=True)

    panel_path = DATA_PROCESSED / "ownership_panel.csv"
    if not panel_path.exists():
        raise FileNotFoundError("ownership_panel.csv가 없습니다. 먼저 05_clean_merge.py를 실행하세요.")

    logger.info("ownership_panel.csv 로드 중...")
    df = pd.read_csv(panel_path)
    df["year"] = df["year"].astype(str)
    logger.info(f"  {len(df)}개 관측치 로드")

    # 전체 통계
    stats_total = compute_yearly_stats(df, "전체")
    stats_total.to_csv(DATA_OUTPUT / "yearly_stats_total.csv", index=False, encoding="utf-8-sig")
    logger.info("저장: yearly_stats_total.csv")

    # KOSPI 통계
    stats_kospi = compute_yearly_stats(df[df["market"] == "KOSPI"], "KOSPI")
    stats_kospi.to_csv(DATA_OUTPUT / "yearly_stats_kospi.csv", index=False, encoding="utf-8-sig")
    logger.info("저장: yearly_stats_kospi.csv")

    # KOSDAQ 통계
    stats_kosdaq = compute_yearly_stats(df[df["market"] == "KOSDAQ"], "KOSDAQ")
    stats_kosdaq.to_csv(DATA_OUTPUT / "yearly_stats_kosdaq.csv", index=False, encoding="utf-8-sig")
    logger.info("저장: yearly_stats_kosdaq.csv")

    # 주요 지표 출력
    logger.info("\n=== 연도별 주요 지표 (전체) ===")
    for _, row in stats_total.iterrows():
        logger.info(
            f"  {row['year']}: 최대주주 {row.get('largest_pct_mean', 0):.1f}% | "
            f"우호지분 {row.get('friendly_pct_mean', 0):.1f}% | "
            f"과반미달(최대주주) {row.get('pct_below50_largest', 0):.1f}% | "
            f"n={row['n']}"
        )

    # 벤치마크 비교
    compare_benchmark(df)


if __name__ == "__main__":
    main()
