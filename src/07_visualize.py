#!/usr/bin/env python3
"""소유구조 분석 결과 시각화 — 5종 차트 생성."""

import logging
import platform
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
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

# 색상 팔레트
COLORS = {
    "largest": "#2563EB",    # blue
    "related": "#7C3AED",   # purple
    "treasury": "#059669",  # green
    "esop": "#D97706",      # amber
    "friendly": "#DC2626",  # red
    "voting": "#0891B2",    # cyan
    "kospi": "#2563EB",
    "kosdaq": "#DC2626",
}


def setup_korean_font() -> None:
    """한글 폰트 설정."""
    font_candidates = [
        "NanumGothic", "Malgun Gothic", "AppleGothic",
        "NanumBarunGothic", "Noto Sans CJK KR",
    ]

    # 시스템 폰트 탐색
    system_fonts = [f.name for f in fm.fontManager.ttflist]

    for font_name in font_candidates:
        if font_name in system_fonts:
            plt.rcParams["font.family"] = font_name
            plt.rcParams["axes.unicode_minus"] = False
            logger.info(f"한글 폰트: {font_name}")
            return

    # 폰트 파일 직접 탐색
    for fpath in Path("/usr/share/fonts").rglob("*.ttf"):
        if "nanum" in fpath.name.lower() or "gothic" in fpath.name.lower():
            fm.fontManager.addfont(str(fpath))
            prop = fm.FontProperties(fname=str(fpath))
            plt.rcParams["font.family"] = prop.get_name()
            plt.rcParams["axes.unicode_minus"] = False
            logger.info(f"한글 폰트: {prop.get_name()} ({fpath})")
            return

    logger.warning("한글 폰트를 찾지 못했습니다. 기본 폰트 사용.")
    plt.rcParams["axes.unicode_minus"] = False


def load_data() -> pd.DataFrame:
    """패널 데이터 로드."""
    path = DATA_PROCESSED / "ownership_panel.csv"
    if not path.exists():
        raise FileNotFoundError("ownership_panel.csv가 없습니다.")
    df = pd.read_csv(path)
    df["year"] = df["year"].astype(int)
    return df


def chart1_stacked_area(df: pd.DataFrame) -> None:
    """1. Stacked Area: 연도별 소유구조 분해 (전체)."""
    yearly = df.groupby("year").agg(
        largest=("largest_pct", "mean"),
        related=("related_pct", "mean"),
        treasury=("treasury_pct", "mean"),
        esop=("esop_pct", "mean"),
    ).fillna(0)

    fig, ax = plt.subplots(figsize=(12, 6))
    years = yearly.index
    ax.stackplot(
        years,
        yearly["largest"], yearly["related"], yearly["treasury"], yearly["esop"],
        labels=["최대주주", "특수관계인", "자사주", "우리사주"],
        colors=[COLORS["largest"], COLORS["related"], COLORS["treasury"], COLORS["esop"]],
        alpha=0.85,
    )
    ax.set_xlabel("연도", fontsize=12)
    ax.set_ylabel("지분율 (%)", fontsize=12)
    ax.set_title("연도별 소유구조 분해 (전체 상장사 평균)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper right", fontsize=10)
    ax.set_xlim(years.min(), years.max())
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(DATA_OUTPUT / "chart1_stacked_area.png", dpi=300)
    plt.close(fig)
    logger.info("저장: chart1_stacked_area.png")


def chart2_line_trend(df: pd.DataFrame) -> None:
    """2. Line Chart: 최대주주 vs 우호지분 추이 (KOSPI/KOSDAQ subplot)."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

    for ax, market, title in [
        (ax1, "KOSPI", "KOSPI"),
        (ax2, "KOSDAQ", "KOSDAQ"),
    ]:
        sub = df[df["market"] == market].groupby("year").agg(
            largest=("largest_pct", "mean"),
            friendly=("friendly_pct", "mean"),
            voting=("voting_friendly_pct", "mean"),
        )
        ax.plot(sub.index, sub["largest"], "-o", color=COLORS["largest"],
                label="최대주주", markersize=4, linewidth=2)
        ax.plot(sub.index, sub["friendly"], "-s", color=COLORS["friendly"],
                label="우호지분", markersize=4, linewidth=2)
        ax.plot(sub.index, sub["voting"], "--^", color=COLORS["voting"],
                label="의결권 기준", markersize=4, linewidth=1.5)
        ax.axhline(y=50, color="gray", linestyle=":", alpha=0.5, label="50% 기준선")
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xlabel("연도", fontsize=11)
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

    ax1.set_ylabel("지분율 (%)", fontsize=11)
    fig.suptitle("최대주주 vs 우호지분 vs 의결권 기준 추이", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(DATA_OUTPUT / "chart2_line_trend.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("저장: chart2_line_trend.png")


def chart3_bar_comparison(df: pd.DataFrame) -> None:
    """3. Bar Chart: KOSPI vs KOSDAQ 우호지분 비교."""
    pivot = df.groupby(["year", "market"])["friendly_pct"].mean().unstack(fill_value=0)

    years = pivot.index
    x = np.arange(len(years))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))
    if "KOSPI" in pivot.columns:
        ax.bar(x - width / 2, pivot["KOSPI"], width, label="KOSPI",
               color=COLORS["kospi"], alpha=0.85)
    if "KOSDAQ" in pivot.columns:
        ax.bar(x + width / 2, pivot["KOSDAQ"], width, label="KOSDAQ",
               color=COLORS["kosdaq"], alpha=0.85)

    ax.set_xlabel("연도", fontsize=12)
    ax.set_ylabel("우호지분율 (%)", fontsize=12)
    ax.set_title("KOSPI vs KOSDAQ 우호지분 비교", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(years, rotation=45)
    ax.legend(fontsize=11)
    ax.axhline(y=50, color="gray", linestyle=":", alpha=0.5)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(DATA_OUTPUT / "chart3_bar_comparison.png", dpi=300)
    plt.close(fig)
    logger.info("저장: chart3_bar_comparison.png")


def chart4_histogram(df: pd.DataFrame) -> None:
    """4. Histogram: 최신 연도 지분율 분포 (KOSPI/KOSDAQ 겹침)."""
    latest_year = df["year"].max()
    df_latest = df[df["year"] == latest_year]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    for ax, col, title in [
        (ax1, "largest_pct", f"최대주주 지분율 분포 ({latest_year}년)"),
        (ax2, "friendly_pct", f"우호지분 분포 ({latest_year}년)"),
    ]:
        kospi = df_latest[df_latest["market"] == "KOSPI"][col].dropna()
        kosdaq = df_latest[df_latest["market"] == "KOSDAQ"][col].dropna()

        bins = np.arange(0, 105, 5)
        ax.hist(kospi, bins=bins, alpha=0.6, label=f"KOSPI (n={len(kospi)})",
                color=COLORS["kospi"], edgecolor="white")
        ax.hist(kosdaq, bins=bins, alpha=0.6, label=f"KOSDAQ (n={len(kosdaq)})",
                color=COLORS["kosdaq"], edgecolor="white")
        ax.set_xlabel("지분율 (%)", fontsize=11)
        ax.set_ylabel("기업 수", fontsize=11)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.legend(fontsize=10)
        ax.axvline(x=50, color="gray", linestyle=":", alpha=0.5)
        ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(DATA_OUTPUT / "chart4_histogram.png", dpi=300)
    plt.close(fig)
    logger.info("저장: chart4_histogram.png")


def chart5_boxplot(df: pd.DataFrame) -> None:
    """5. Box Plot: 연도별 최대주주 지분율 분포 변화."""
    years = sorted(df["year"].unique())

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    for ax, market, title in [
        (ax1, "KOSPI", "KOSPI — 연도별 최대주주 지분율 분포"),
        (ax2, "KOSDAQ", "KOSDAQ — 연도별 최대주주 지분율 분포"),
    ]:
        sub = df[df["market"] == market]
        data_by_year = [sub[sub["year"] == y]["largest_pct"].dropna().values for y in years]

        bp = ax.boxplot(
            data_by_year,
            labels=years,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "black", "linewidth": 1.5},
        )
        color = COLORS["kospi"] if market == "KOSPI" else COLORS["kosdaq"]
        for patch in bp["boxes"]:
            patch.set_facecolor(color)
            patch.set_alpha(0.6)

        ax.axhline(y=50, color="gray", linestyle=":", alpha=0.5)
        ax.set_ylabel("최대주주 지분율 (%)", fontsize=11)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(DATA_OUTPUT / "chart5_boxplot.png", dpi=300)
    plt.close(fig)
    logger.info("저장: chart5_boxplot.png")


def main() -> None:
    DATA_OUTPUT.mkdir(parents=True, exist_ok=True)
    setup_korean_font()

    df = load_data()
    logger.info(f"패널 데이터 {len(df)}행 로드")

    chart1_stacked_area(df)
    chart2_line_trend(df)
    chart3_bar_comparison(df)
    chart4_histogram(df)
    chart5_boxplot(df)

    logger.info("모든 차트 생성 완료!")


if __name__ == "__main__":
    main()
