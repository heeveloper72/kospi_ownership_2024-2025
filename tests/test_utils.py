"""utils.py 함수 유닛 테스트."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import utils


# ─────────────────────────────────────────────
# load_checkpoint / save_checkpoint
# ─────────────────────────────────────────────

class TestCheckpoint:
    def test_load_missing_file_returns_defaults(self, tmp_path):
        cp = utils.load_checkpoint(tmp_path / "no_such.json")
        assert cp["completed"] == {}
        assert cp["date"] == str(date.today())

    def test_load_existing_dict_format(self, tmp_path):
        path = tmp_path / "cp.json"
        data = {
            "completed": {"A001": ["2023", "2022"]},
            "date": str(date.today()),
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        cp = utils.load_checkpoint(path)
        assert cp["completed"]["A001"] == ["2023", "2022"]

    def test_load_old_list_format_auto_converts(self, tmp_path):
        """구 형식(list of pairs)을 자동으로 dict로 변환."""
        path = tmp_path / "cp.json"
        data = {
            "completed": [["A001", "2023"], ["A001", "2022"], ["B002", "2023"]],
            "calls_today": 500,
            "date": str(date.today()),
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        cp = utils.load_checkpoint(path)
        assert isinstance(cp["completed"], dict)
        assert "2023" in cp["completed"]["A001"]
        assert "2022" in cp["completed"]["A001"]
        assert "2023" in cp["completed"]["B002"]

    def test_save_and_reload(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = {"completed": {"B001": ["2022"]}, "date": "2099-01-01"}
        utils.save_checkpoint(path, cp)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["completed"]["B001"] == ["2022"]


# ─────────────────────────────────────────────
# mark_completed / is_completed
# ─────────────────────────────────────────────

class TestCompletedHelpers:
    def test_mark_and_check(self):
        cp = {"completed": {}}
        utils.mark_completed(cp, "A001", "2023")
        assert utils.is_completed(cp, "A001", "2023")
        assert not utils.is_completed(cp, "A001", "2022")
        assert not utils.is_completed(cp, "B002", "2023")

    def test_mark_idempotent(self):
        cp = {"completed": {}}
        utils.mark_completed(cp, "A001", "2023")
        utils.mark_completed(cp, "A001", "2023")
        assert cp["completed"]["A001"].count("2023") == 1


# ─────────────────────────────────────────────
# load_daily_counter / save_daily_counter
# ─────────────────────────────────────────────

class TestDailyCounter:
    def test_missing_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(utils, "DAILY_COUNTER_PATH", tmp_path / "counter.json")
        monkeypatch.setattr(utils, "DATA_RAW", tmp_path)
        counter = utils.load_daily_counter()
        assert counter["calls"] == 0
        assert counter["date"] == str(date.today())

    def test_old_date_resets(self, tmp_path, monkeypatch):
        counter_path = tmp_path / "counter.json"
        monkeypatch.setattr(utils, "DAILY_COUNTER_PATH", counter_path)
        monkeypatch.setattr(utils, "DATA_RAW", tmp_path)
        counter_path.write_text(
            json.dumps({"date": "2000-01-01", "calls": 9999}), encoding="utf-8"
        )
        counter = utils.load_daily_counter()
        assert counter["calls"] == 0

    def test_save_and_reload(self, tmp_path, monkeypatch):
        counter_path = tmp_path / "counter.json"
        monkeypatch.setattr(utils, "DAILY_COUNTER_PATH", counter_path)
        monkeypatch.setattr(utils, "DATA_RAW", tmp_path)
        counter = {"date": str(date.today()), "calls": 42}
        utils.save_daily_counter(counter)
        reloaded = utils.load_daily_counter()
        assert reloaded["calls"] == 42

    def test_is_daily_limit_reached(self):
        assert utils.is_daily_limit_reached({"calls": 10000})
        assert utils.is_daily_limit_reached({"calls": 99999})
        assert not utils.is_daily_limit_reached({"calls": 9999})


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
        utils.append_to_csv(path, [{"corp_code": "001", "name": "A", "value": "1"}], self.FIELDS)
        utils.append_to_csv(path, [{"corp_code": "002", "name": "B", "value": "2"}], self.FIELDS)
        lines = [l for l in path.read_text(encoding="utf-8-sig").strip().splitlines() if l]
        assert len(lines) == 3  # 헤더 1 + 데이터 2

    def test_empty_rows_does_not_crash(self, tmp_path):
        utils.append_to_csv(tmp_path / "out.csv", [], self.FIELDS)


# ─────────────────────────────────────────────
# parse_rate (05_clean_merge.py)
# ─────────────────────────────────────────────

class TestParseRate:
    @pytest.fixture(autouse=True)
    def import_parse_rate(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "clean_merge", SRC_DIR / "05_clean_merge.py"
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
