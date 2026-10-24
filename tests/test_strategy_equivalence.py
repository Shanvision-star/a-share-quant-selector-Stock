"""逐股逐策略对照工具的离线验收，不读取正式行情或启动进程池。"""

import copy
import os

import pytest

from scripts.verify_strategy_equivalence import (
    compare_legacy_rows,
    compare_rows,
    content_manifest,
    validate_coverage,
)


def _row(code="000001", status="matched"):
    hits = {} if status != "matched" else {
        "b1": {"strategy_name": "B1", "stock_result": {
            "code": code, "name": "示例", "signals": [{"date": "2026-10-23", "close": 10.0}],
        }}
    }
    return {
        "code": code, "name": "示例", "status": "ok", "reason": None,
        "hits": hits,
        "outcomes": {"b1": {"strategy_name": "B1", "status": status,
                              "signal_count": int(status == "matched"), "elapsed_seconds": 0.3}},
    }


def test_comparison_ignores_only_declared_runtime_fields():
    expected = _row()
    actual = copy.deepcopy(expected)
    actual["outcomes"]["b1"]["elapsed_seconds"] = 2.0
    actual["timings_seconds"] = {"read": 0.1}
    assert compare_rows([expected], [actual])["equal"]
    actual["hits"]["b1"]["stock_result"]["signals"][0]["elapsed_seconds"] = 2.0
    assert not compare_rows([expected], [actual])["equal"]


def test_comparison_is_exact_and_reports_per_strategy_path():
    expected = _row()
    actual = copy.deepcopy(expected)
    actual["hits"]["b1"]["stock_result"]["signals"][0]["close"] = 10.000000000001
    result = compare_rows([expected], [actual])
    assert not result["equal"]
    assert result["changed_codes"] == ["000001"]
    assert "hits.b1.stock_result.signals[0].close" in result["differences"][0]["path"]


def test_comparison_accepts_stock_completion_order_but_rejects_duplicates():
    rows = [_row("000001"), _row("000002")]
    assert compare_rows(rows, list(reversed(rows)))["equal"]
    with pytest.raises(ValueError, match="重复"):
        compare_rows(rows, [rows[0], rows[0]])


def test_coverage_requires_every_stock_strategy_and_consistent_hits():
    result = validate_coverage([_row()], ["000001", "000002"], ["b1", "b2"])
    assert not result["valid"]
    assert result["missing_codes"] == ["000002"]
    assert any("b2" in error for error in result["violations"])
    row = _row()
    row["outcomes"]["b1"]["status"] = "not_matched"
    assert not validate_coverage([row], ["000001"], ["b1"])["valid"]


def test_equal_errors_are_recorded_but_never_accepted_as_success():
    row = _row(status="error")
    row["status"] = "error"
    row["outcomes"]["b1"].update(error_type="ValueError", error_message="坏数据")
    assert compare_rows([row], [copy.deepcopy(row)])["equal"]
    coverage = validate_coverage([row], ["000001"], ["b1"])
    assert coverage["valid"]
    assert coverage["error_count"] == 1
    assert not coverage["successful"]


def test_skipped_and_unmatched_are_distinct_terminal_states():
    unmatched, skipped = _row(status="not_matched"), _row(status="skipped")
    skipped.update(status="skip", reason="数据不足")
    skipped["outcomes"]["b1"]["reason"] = "数据不足"
    assert validate_coverage([skipped], ["000001"], ["b1"])["successful"]
    assert not compare_rows([unmatched], [skipped])["equal"]


def test_coverage_rejects_wrong_stock_and_future_signal():
    row = _row()
    row["hits"]["b1"]["stock_result"]["code"] = "000002"
    assert not validate_coverage([row], ["000001"], ["b1"])["valid"]
    row = _row()
    result = validate_coverage([row], ["000001"], ["b1"], "2026-10-22")
    assert not result["valid"]
    assert any("晚于目标日" in violation for violation in result["violations"])


def test_content_manifest_detects_change_with_same_size_and_mtime(tmp_path):
    path = tmp_path / "bars.csv"
    path.write_bytes(b"date,close\n2026-10-23,10\n")
    original_stat = path.stat()
    before = content_manifest({"bars": path})
    path.write_bytes(b"date,close\n2026-10-23,11\n")
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    after = content_manifest({"bars": path})
    assert before["files"]["bars"]["size"] == after["files"]["bars"]["size"]
    assert before["files"]["bars"]["mtime_ns"] == after["files"]["bars"]["mtime_ns"]
    assert before["sha256"] != after["sha256"]


def test_legacy_comparison_does_not_invent_outcomes():
    current = _row()
    legacy = {key: value for key, value in current.items() if key != "outcomes"}
    result = compare_legacy_rows([legacy], [current])
    assert result["equal_on_legacy_fields"]
    assert result["legacy_outcome_coverage"] == "unavailable"
    changed = copy.deepcopy(current)
    changed["hits"] = {}
    assert not compare_legacy_rows([legacy], [changed])["equal_on_legacy_fields"]


def test_manifest_missing_file_is_explicit_and_stable(tmp_path):
    result = content_manifest({"bars": tmp_path / "missing.csv"})
    assert result["files"]["bars"] == {"exists": False}
