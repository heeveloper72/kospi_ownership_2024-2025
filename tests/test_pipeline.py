"""픽스처 데이터로 05→06→07→10 파이프라인 통합 테스트."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SRC_DIR))


def load_module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, SRC_DIR / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def pipeline_dirs(tmp_path):
    """픽스처 파일을 tmp_path/data/raw/ 에 복사하고 경로를 패치한 뒤 yield."""
    raw = tmp_path / "data" / "raw"
    processed = tmp_path / "data" / "processed"
    output = tmp_path / "data" / "output"
    raw.mkdir(parents=True)
    processed.mkdir(parents=True)
    output.mkdir(parents=True)

    for csv_file in FIXTURES_DIR.glob("*.csv"):
        shutil.copy(csv_file, raw / csv_file.name)

    return {"raw": raw, "processed": processed, "output": output, "base": tmp_path}


# ─────────────────────────────────────────────
# 05_clean_merge.py
# ─────────────────────────────────────────────

class TestCleanMerge:
    def test_creates_ownership_panel(self, pipeline_dirs, monkeypatch):
        mod = load_module("clean_merge", "05_clean_merge.py")
        monkeypatch.setattr(mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])

        mod.main()

        panel_path = pipeline_dirs["processed"] / "ownership_panel.csv"
        assert panel_path.exists(), "ownership_panel.csv가 생성되어야 함"

        df = pd.read_csv(panel_path)
        expected_cols = {"corp_code", "corp_name", "market", "year",
                         "largest_pct", "related_pct", "treasury_pct",
                         "esop_pct", "friendly_pct", "voting_friendly_pct"}
        assert expected_cols.issubset(df.columns)
        assert len(df) > 0

    def test_kospi_kosdaq_both_present(self, pipeline_dirs, monkeypatch):
        mod = load_module("clean_merge", "05_clean_merge.py")
        monkeypatch.setattr(mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])

        mod.main()

        df = pd.read_csv(pipeline_dirs["processed"] / "ownership_panel.csv")
        assert "KOSPI" in df["market"].values
        assert "KOSDAQ" in df["market"].values

    def test_friendly_pct_computed(self, pipeline_dirs, monkeypatch):
        mod = load_module("clean_merge", "05_clean_merge.py")
        monkeypatch.setattr(mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])

        mod.main()

        df = pd.read_csv(pipeline_dirs["processed"] / "ownership_panel.csv")
        # friendly_pct >= largest_pct (특수관계인 등 더해지므로)
        valid = df.dropna(subset=["friendly_pct", "largest_pct"])
        assert (valid["friendly_pct"] >= valid["largest_pct"]).all()


# ─────────────────────────────────────────────
# 06_analyze.py
# ─────────────────────────────────────────────

class TestAnalyze:
    def _prepare_panel(self, pipeline_dirs, monkeypatch):
        clean_mod = load_module("clean_merge", "05_clean_merge.py")
        monkeypatch.setattr(clean_mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(clean_mod, "DATA_PROCESSED", pipeline_dirs["processed"])
        clean_mod.main()

    def test_creates_three_stat_files(self, pipeline_dirs, monkeypatch):
        self._prepare_panel(pipeline_dirs, monkeypatch)

        mod = load_module("analyze", "06_analyze.py")
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])
        monkeypatch.setattr(mod, "DATA_OUTPUT", pipeline_dirs["output"])

        mod.main()

        for fname in ["yearly_stats_total.csv", "yearly_stats_kospi.csv", "yearly_stats_kosdaq.csv"]:
            assert (pipeline_dirs["output"] / fname).exists(), f"{fname}이 생성되어야 함"

    def test_stat_files_have_expected_columns(self, pipeline_dirs, monkeypatch):
        self._prepare_panel(pipeline_dirs, monkeypatch)

        mod = load_module("analyze", "06_analyze.py")
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])
        monkeypatch.setattr(mod, "DATA_OUTPUT", pipeline_dirs["output"])

        mod.main()

        df = pd.read_csv(pipeline_dirs["output"] / "yearly_stats_total.csv")
        assert "year" in df.columns
        assert "largest_pct_mean" in df.columns
        assert "friendly_pct_mean" in df.columns


# ─────────────────────────────────────────────
# 07_visualize.py
# ─────────────────────────────────────────────

class TestVisualize:
    def _prepare_panel(self, pipeline_dirs, monkeypatch):
        clean_mod = load_module("clean_merge2", "05_clean_merge.py")
        monkeypatch.setattr(clean_mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(clean_mod, "DATA_PROCESSED", pipeline_dirs["processed"])
        clean_mod.main()

    def test_creates_five_charts(self, pipeline_dirs, monkeypatch):
        self._prepare_panel(pipeline_dirs, monkeypatch)

        mod = load_module("visualize", "07_visualize.py")
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])
        monkeypatch.setattr(mod, "DATA_OUTPUT", pipeline_dirs["output"])

        mod.main()

        for i in range(1, 6):
            chart = list(pipeline_dirs["output"].glob(f"chart{i}_*.png"))
            assert len(chart) == 1, f"chart{i}_*.png 가 생성되어야 함"


# ─────────────────────────────────────────────
# 10_compute_tobin_q.py
# ─────────────────────────────────────────────

class TestTobinQ:
    def test_creates_financial_panel(self, pipeline_dirs, monkeypatch):
        mod = load_module("tobin_q", "10_compute_tobin_q.py")
        monkeypatch.setattr(mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])

        mod.main()

        out = pipeline_dirs["processed"] / "financial_panel.csv"
        assert out.exists(), "financial_panel.csv가 생성되어야 함"

        df = pd.read_csv(out)
        expected = {"corp_code", "year", "total_assets", "total_liabilities",
                    "tobin_q", "leverage", "size", "roa"}
        assert expected.issubset(df.columns)
        assert len(df) > 0

    def test_tobin_q_positive_for_valid_rows(self, pipeline_dirs, monkeypatch):
        mod = load_module("tobin_q2", "10_compute_tobin_q.py")
        monkeypatch.setattr(mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])

        mod.main()

        df = pd.read_csv(pipeline_dirs["processed"] / "financial_panel.csv")
        valid = df.dropna(subset=["tobin_q"])
        assert len(valid) > 0, "Tobin Q 유효값이 하나 이상 있어야 함"
        # Tobin Q > 0 (시가총액 + 부채 > 0, 자산 > 0)
        assert (valid["tobin_q"] > 0).all()

    def test_leverage_between_0_and_1(self, pipeline_dirs, monkeypatch):
        mod = load_module("tobin_q3", "10_compute_tobin_q.py")
        monkeypatch.setattr(mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])

        mod.main()

        df = pd.read_csv(pipeline_dirs["processed"] / "financial_panel.csv")
        valid = df.dropna(subset=["leverage"])
        assert ((valid["leverage"] >= 0) & (valid["leverage"] <= 1)).all()

    def test_creates_ownership_financial_panel_when_panel_exists(self, pipeline_dirs, monkeypatch):
        # 먼저 ownership_panel.csv 생성
        clean_mod = load_module("clean_merge3", "05_clean_merge.py")
        monkeypatch.setattr(clean_mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(clean_mod, "DATA_PROCESSED", pipeline_dirs["processed"])
        clean_mod.main()

        mod = load_module("tobin_q4", "10_compute_tobin_q.py")
        monkeypatch.setattr(mod, "DATA_RAW", pipeline_dirs["raw"])
        monkeypatch.setattr(mod, "DATA_PROCESSED", pipeline_dirs["processed"])

        mod.main()

        out = pipeline_dirs["processed"] / "ownership_financial_panel.csv"
        assert out.exists(), "ownership_financial_panel.csv가 생성되어야 함"
        df = pd.read_csv(out)
        assert "tobin_q" in df.columns
        assert "largest_pct" in df.columns
