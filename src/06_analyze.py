#!/usr/bin/env python3
"""소유구조 패널 데이터의 통계 분석 및 벤치마크 비교."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

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

# H4 클러스터링 입력 피처
CLUSTER_FEATURES = ["largest_pct", "related_pct", "treasury_pct", "friendly_pct"]
CLUSTER_K_RANGE = range(2, 7)
CLUSTER_RANDOM_STATE = 42


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


def run_h4_clustering(df: pd.DataFrame) -> pd.DataFrame:
    """H4: 소유구조 4차원(largest/related/treasury/friendly)에 PCA+GMM 적용.

    반환: corp_code, year, 피처, cluster_label, pc1, pc2 컬럼을 포함한 데이터프레임.
    산출물: cluster_labels_by_year.csv, pca_loadings.csv, bic_aic_scores.csv
    """
    missing = [c for c in CLUSTER_FEATURES if c not in df.columns]
    if missing:
        logger.warning(f"H4 클러스터링 스킵 — 피처 누락: {missing}")
        return pd.DataFrame()

    valid_mask = df[CLUSTER_FEATURES].notna().all(axis=1)
    sanity_mask = (df["largest_pct"] > 0) & (df["friendly_pct"] <= 100)
    work = df[valid_mask & sanity_mask].copy()
    logger.info(f"H4 입력: 전체 {len(df)} → 유효 관측치 {len(work)}")

    if len(work) < 50:
        logger.warning(f"H4 클러스터링 스킵 — 유효 관측치 부족 ({len(work)})")
        return pd.DataFrame()

    X = work[CLUSTER_FEATURES].to_numpy()
    scaler = StandardScaler()
    X_std = scaler.fit_transform(X)

    pca = PCA(n_components=2, random_state=CLUSTER_RANDOM_STATE)
    X_pca = pca.fit_transform(X_std)
    logger.info(
        f"PCA 설명분산: PC1={pca.explained_variance_ratio_[0]:.3f}, "
        f"PC2={pca.explained_variance_ratio_[1]:.3f}, "
        f"누적={pca.explained_variance_ratio_.sum():.3f}"
    )

    # BIC/AIC로 k 선택
    scores = []
    for k in CLUSTER_K_RANGE:
        gmm = GaussianMixture(
            n_components=k, covariance_type="full",
            random_state=CLUSTER_RANDOM_STATE, n_init=5, max_iter=200,
        )
        gmm.fit(X_std)
        scores.append({"k": k, "bic": gmm.bic(X_std), "aic": gmm.aic(X_std),
                       "converged": bool(gmm.converged_)})
    bic_df = pd.DataFrame(scores)
    best_k = int(bic_df.loc[bic_df["bic"].idxmin(), "k"])
    logger.info(f"GMM 최적 k (BIC 최소): {best_k}")
    bic_df.to_csv(DATA_OUTPUT / "bic_aic_scores.csv", index=False, encoding="utf-8-sig")

    gmm = GaussianMixture(
        n_components=best_k, covariance_type="full",
        random_state=CLUSTER_RANDOM_STATE, n_init=5, max_iter=200,
    )
    labels = gmm.fit_predict(X_std)

    work["cluster_label"] = labels.astype(int)
    work["pc1"] = X_pca[:, 0]
    work["pc2"] = X_pca[:, 1]

    keep_cols = ["corp_code", "corp_name", "market", "year",
                 *CLUSTER_FEATURES, "cluster_label", "pc1", "pc2"]
    existing_cols = [c for c in keep_cols if c in work.columns]
    work[existing_cols].to_csv(
        DATA_OUTPUT / "cluster_labels_by_year.csv",
        index=False, encoding="utf-8-sig",
    )

    loadings = pd.DataFrame(
        pca.components_.T,
        index=CLUSTER_FEATURES,
        columns=["PC1", "PC2"],
    )
    loadings.loc["explained_variance_ratio", "PC1"] = pca.explained_variance_ratio_[0]
    loadings.loc["explained_variance_ratio", "PC2"] = pca.explained_variance_ratio_[1]
    loadings.to_csv(DATA_OUTPUT / "pca_loadings.csv", encoding="utf-8-sig")

    cluster_summary = work.groupby("cluster_label")[CLUSTER_FEATURES].mean().round(2)
    logger.info(f"\n=== 클러스터별 평균 ({best_k}개 클러스터) ===\n{cluster_summary}")

    return work


def compute_transition_matrix(labeled: pd.DataFrame) -> pd.DataFrame:
    """기업별 연도 t → t+1 클러스터 전이 확률 행렬."""
    if labeled.empty or "cluster_label" not in labeled.columns:
        return pd.DataFrame()

    tmp = labeled[["corp_code", "year", "cluster_label"]].copy()
    tmp["year_int"] = pd.to_numeric(tmp["year"], errors="coerce").astype("Int64")
    tmp = tmp.dropna(subset=["year_int"]).sort_values(["corp_code", "year_int"])

    transitions = []
    for corp_code, grp in tmp.groupby("corp_code"):
        prev_label = None
        prev_year = None
        for _, row in grp.iterrows():
            year = int(row["year_int"])
            label = int(row["cluster_label"])
            if prev_label is not None and year == prev_year + 1:
                transitions.append({"from": prev_label, "to": label})
            prev_label = label
            prev_year = year

    if not transitions:
        logger.warning("전이쌍 없음 — Markov 전이행렬 스킵")
        return pd.DataFrame()

    trans_df = pd.DataFrame(transitions)
    counts = trans_df.groupby(["from", "to"]).size().unstack(fill_value=0).sort_index()
    counts = counts.reindex(columns=sorted(counts.columns.union(counts.index)), fill_value=0)
    counts = counts.reindex(index=counts.columns, fill_value=0)
    row_sums = counts.sum(axis=1).replace(0, np.nan)
    probs = counts.div(row_sums, axis=0).fillna(0).round(4)

    probs.to_csv(DATA_OUTPUT / "transition_matrix.csv", encoding="utf-8-sig")
    counts.to_csv(DATA_OUTPUT / "transition_counts.csv", encoding="utf-8-sig")
    logger.info(f"Markov 전이행렬 ({probs.shape[0]}x{probs.shape[1]}) 저장: transition_matrix.csv")
    logger.info(f"\n=== 대각(지속성) 확률 ===\n{pd.Series(np.diag(probs), index=probs.index).round(3)}")
    return probs


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

    # H4: PCA + GMM 클러스터링 + Markov 전이행렬
    logger.info("\n=== H4 클러스터링 (PCA + GMM) ===")
    labeled = run_h4_clustering(df)
    if not labeled.empty:
        compute_transition_matrix(labeled)


if __name__ == "__main__":
    main()
