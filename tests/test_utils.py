"""utils.py 함수 유닛 테스트."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# src/ 경로를 sys.path에 추가
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import utils


# ─────────────────────────────────────────────
# load_checkpoint / save_checkpoint
# ─────────────────────────────────────────────

class TestCheckpoint:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        cp = utils.load_checkpoint(tmp_path / "no_such.json")
        assert cp["completed"] == []
        assert cp["calls_today"] == 0
        assert cp["date"] == str(date.today())

    def test_load_existing_same_date(self, tmp_path):
        path = tmp_path / "cp.json"
        data = {
            "completed": [["A001", "2023"]],
            "calls_today": 500,
            "date": str(date.today()),
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        cp = utils.load_checkpoint(path)
        assert cp["calls_today"] == 500

    def test_load_old_date_resets_calls_today(self, tmp_path):
        path = tmp_path / "cp.json"
        yesterday = str(date.today() - timedelta(days=1))
        data = {
            "completed": [["A001", "2023"]],
            "calls_today": 9999,
            "date": yesterday,
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        cp = utils.load_checkpoint(path)
        assert cp["calls_today"] == 0
        assert cp["date"] == str(date.today())

    def test_save_and_reload(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = {"completed": [["B001", "2022"]], "calls_today": 42, "date": "2099-01-01"}
        utils.save_checkpoint(path, cp)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["calls_today"] == 42
        assert loaded["completed"] == [["B001", "2022"]]


# ─────────────────────────────────────────────
# append_to_csv
# ─────────────────────────────────────────────

class TestAppendToCsv:
    FIELDS = ["corp_code", "name", "value"]

    def test_creates_file_with_header(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"corp_code": "001", "name": "테스트", "value": "10.5"}]
        utils.append_to_csv(path, rows, self.FIELDS)
        lines = path.read_text(encoding="utf-8-sig").strip().splitlines()
        assert lines[0].startswith("corp_code")
        assert "001" in lines[1]

    def test_appends_without_duplicate_header(self, tmp_path):
        path = tmp_path / "out.csv"
        rows1 = [{"corp_code": "001", "name": "A", "value": "1"}]
        rows2 = [{"corp_code": "002", "name": "B", "value": "2"}]
        utils.append_to_csv(path, rows1, self.FIELDS)
        utils.append_to_csv(path, rows2, self.FIELDS)
        lines = [l for l in path.read_text(encoding="utf-8-sig").strip().splitlines() if l]
        # 헤더 1줄 + 데이터 2줄 = 3줄
        assert len(lines) == 3

    def test_empty_rows_does_not_crash(self, tmp_path):
        path = tmp_path / "out.csv"
        utils.append_to_csv(path, [], self.FIELDS)
        # 파일 없거나 빈 상태여도 오류 없어야 함


# ─────────────────────────────────────────────
# parse_rate (05_clean_merge.py)
# ─────────────────────────────────────────────

class TestParseRate:
    @pytest.fixture(autouse=True)
    def import_parse_rate(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "clean_merge",
            SRC_DIR / "05_clean_merge.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.parse_rate = mod.parse_rate

    def test_plain_number(self):
        assert self.parse_rate("29.21") == pytest.approx(29.21)

    def test_number_with_comma(self):
        assert self.parse_rate("1,234.56") == pytest.approx(1234.56)

    def test_number_with_percent(self):
        assert self.parse_rate("43.07%") == pytest.approx(43.07)

    def test_dash_returns_nan(self):
        import math
        assert math.isnan(self.parse_rate("-"))

    def test_empty_string_returns_nan(self):
        import math
        assert math.isnan(self.parse_rate(""))

    def test_nan_input_returns_nan(self):
        import math
        import numpy as np
        assert math.isnan(self.parse_rate(np.nan))
