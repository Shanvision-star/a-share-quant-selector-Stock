"""只读验证正式串行与多进程扫描逐股逐策略等价，并保存内容指纹及旧基线差异。"""

from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import copy
from datetime import date
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import pickle
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TERMINAL_STATES = {"matched", "not_matched", "skipped", "error"}


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"无法无损序列化：{type(value).__name__}")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def semantic_row(row):
    result = copy.deepcopy(row)
    # 只排除约定的调度遥测；信号正文内同名字段仍参与精确比较。
    result.pop("timings_seconds", None)
    for outcome in result.get("outcomes", {}).values():
        outcome.pop("elapsed_seconds", None)
    return result


def _index_rows(rows):
    result = {}
    for row in rows:
        code = row.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError("结果缺少股票代码")
        if code in result:
            raise ValueError(f"结果包含重复股票：{code}")
        result[code] = semantic_row(row)
    return result


def _field_differences(expected, actual, path):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}"
            if key not in expected or key not in actual:
                yield {"path": child, "expected_present": key in expected,
                       "actual_present": key in actual,
                       "expected": expected.get(key), "actual": actual.get(key)}
            else:
                yield from _field_differences(expected[key], actual[key], child)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            yield {"path": f"{path}.length", "expected": len(expected), "actual": len(actual)}
        for index, (left, right) in enumerate(zip(expected, actual)):
            yield from _field_differences(left, right, f"{path}[{index}]")
        for index in range(min(len(expected), len(actual)), max(len(expected), len(actual))):
            yield {"path": f"{path}[{index}]", "expected_present": index < len(expected),
                   "actual_present": index < len(actual),
                   "expected": expected[index] if index < len(expected) else None,
                   "actual": actual[index] if index < len(actual) else None}
    elif canonical(expected) != canonical(actual):
        yield {"path": path, "expected": expected, "actual": actual}


def compare_rows(expected, actual):
    left, right = _index_rows(expected), _index_rows(actual)
    differences = []
    changed = []
    for code in sorted(set(left) & set(right)):
        if canonical(left[code]) == canonical(right[code]):
            continue
        changed.append(code)
        differences.extend(_field_differences(left[code], right[code], f"stocks.{code}"))
    missing, extra = sorted(set(left) - set(right)), sorted(set(right) - set(left))
    return {"equal": not (changed or missing or extra), "changed_codes": changed,
            "missing_codes": missing, "extra_codes": extra, "differences": differences,
            "expected_sha256": hashlib.sha256(canonical(left).encode()).hexdigest(),
            "actual_sha256": hashlib.sha256(canonical(right).encode()).hexdigest()}


def validate_coverage(rows, codes, strategies, target_date=None):
    indexed = _index_rows(rows)
    expected_codes, expected_strategies = set(codes), set(strategies)
    missing, extra = sorted(expected_codes - set(indexed)), sorted(set(indexed) - expected_codes)
    violations, counts, errors = [], Counter(), []
    if len(codes) != len(expected_codes) or len(strategies) != len(expected_strategies):
        violations.append("期望的股票或策略列表存在重复")
    for code, row in indexed.items():
        outcomes, hits = row.get("outcomes", {}), row.get("hits", {})
        if set(outcomes) != expected_strategies:
            violations.append(f"{code}: 策略覆盖不同 missing={sorted(expected_strategies - set(outcomes))} extra={sorted(set(outcomes) - expected_strategies)}")
        if set(hits) - expected_strategies:
            violations.append(f"{code}: 出现未请求策略命中")
        stock_errors = 0
        for strategy, outcome in outcomes.items():
            state = outcome.get("status")
            counts[state or "missing"] += 1
            if state not in TERMINAL_STATES:
                violations.append(f"{code}/{strategy}: 未知终态 {state}")
            signals = hits.get(strategy, {}).get("stock_result", {}).get("signals", [])
            if state == "matched":
                if not signals or outcome.get("signal_count") != len(signals):
                    violations.append(f"{code}/{strategy}: 命中与 signal_count 不一致")
                hit = hits.get(strategy, {})
                if hit.get("stock_result", {}).get("code") != code:
                    violations.append(f"{code}/{strategy}: 命中属于其他股票")
                if hit.get("strategy_name") != outcome.get("strategy_name"):
                    violations.append(f"{code}/{strategy}: 命中与终态策略名称不同")
                if target_date is not None:
                    for signal in signals:
                        try:
                            signal_date = date.fromisoformat(str(signal["date"])[:10])
                            if signal_date > date.fromisoformat(target_date):
                                violations.append(f"{code}/{strategy}: 信号日期晚于目标日")
                        except (KeyError, TypeError, ValueError):
                            violations.append(f"{code}/{strategy}: 信号缺少有效日期")
            elif strategy in hits or outcome.get("signal_count") != 0:
                violations.append(f"{code}/{strategy}: 非命中状态仍包含命中或信号计数")
            if state == "skipped" and not (outcome.get("reason") or row.get("reason")):
                violations.append(f"{code}/{strategy}: 跳过未记录原因")
            if state == "error":
                stock_errors += 1
                errors.append({"code": code, "strategy": strategy, **outcome})
                if not outcome.get("error_type") or "error_message" not in outcome:
                    violations.append(f"{code}/{strategy}: 异常信息不完整")
        if bool(stock_errors) != (row.get("status") == "error"):
            violations.append(f"{code}: 股票与策略异常状态不一致")
    valid = not (missing or extra or violations)
    return {"valid": valid, "successful": valid and not errors,
            "stock_count": len(indexed), "expected_stock_count": len(expected_codes),
            "expected_outcomes": len(expected_codes) * len(expected_strategies),
            "actual_outcomes": sum(counts.values()), "counts": dict(counts),
            "missing_codes": missing, "extra_codes": extra, "violations": violations,
            "error_count": len(errors), "errors": errors}


def content_manifest(paths):
    files = {}
    for label, raw_path in sorted(paths.items()):
        path = Path(raw_path)
        if not path.exists():
            files[label] = {"exists": False}
            continue
        before = path.stat()
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"记录指纹期间文件变化：{label}")
        files[label] = {"exists": True, "size": after.st_size,
                        "mtime_ns": after.st_mtime_ns, "sha256": digest}
    return {"files": files, "sha256": hashlib.sha256(canonical(files).encode()).hexdigest()}


def compare_legacy_rows(legacy, corrected):
    keys = ("code", "name", "status", "reason", "hits")
    projected_old = [{key: row[key] for key in keys if key in row} for row in legacy]
    projected_new = [{key: row[key] for key in keys if key in row} for row in corrected]
    comparison = compare_rows(projected_old, projected_new)
    old, new = _index_rows(legacy), _index_rows(corrected)
    changes = []
    for code in comparison["changed_codes"]:
        for strategy in sorted(set(old[code].get("hits", {})) | set(new[code].get("hits", {}))):
            previous = old[code].get("hits", {}).get(strategy)
            current = new[code].get("hits", {}).get(strategy)
            if canonical(previous) == canonical(current):
                continue
            changes.append({"code": code, "strategy": strategy,
                            "previous_signal_dates": [s.get("date") for s in (previous or {}).get("stock_result", {}).get("signals", [])],
                            "corrected_signal_dates": [s.get("date") for s in (current or {}).get("stock_result", {}).get("signals", [])]})
    return {"equal_on_legacy_fields": comparison["equal"],
            "legacy_outcome_coverage": "available" if all("outcomes" in row for row in legacy) else "unavailable",
            "requires_review": not comparison["equal"], "signal_changes": changes, **comparison}


def _input_paths(codes, data_dir):
    paths = {f"market/{code}.csv": data_dir / code[:2] / f"{code}.csv" for code in codes}
    paths["stock_names.json"] = ROOT / "data" / "stock_names.json"
    paths["config/strategy_params.yaml"] = ROOT / "config" / "strategy_params.yaml"
    paths["scripts/verify_strategy_equivalence.py"] = Path(__file__)
    for folder in ("strategy", "utils", "web/backend/services", "third_party/zettaranc"):
        for path in (ROOT / folder).rglob("*.py"):
            paths[path.relative_to(ROOT).as_posix()] = path
    return paths


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               default=_json_default), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=64, help="0 表示所有本地股票")
    parser.add_argument("--codes", help="明确代码，逗号分隔；优先于 count")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--legacy-results", type=Path)
    args = parser.parse_args(argv)
    if args.count < 0 or args.workers < 1 or args.batch_size < 1 or args.timeout_seconds <= 0:
        parser.error("count 不能小于零；workers、batch-size、timeout-seconds 必须大于零")
    args.output.mkdir(parents=True, exist_ok=False)
    # 验证进程与计算子进程都不得触发业务数据库初始化。
    os.environ["QUANT_SCAN_WORKER"] = "1"
    from web.backend.services import strategy_service as service
    from web.backend.services.strategy_scan import iter_scan_results
    with contextlib.redirect_stdout(io.StringIO()):
        names, items = service.get_resolved_strategy_items()
    all_codes = sorted(service.csv_manager.list_all_stocks())
    if args.codes:
        codes = sorted(set(args.codes.split(",")))
        if set(codes) - set(all_codes):
            parser.error("指定股票不存在本地行情")
    elif args.count == 0 or args.count >= len(all_codes):
        codes = all_codes
    else:
        must_include = [code for code in ("000717", "688613", "300987", "688031") if code in all_codes]
        codes = must_include[:args.count]
        codes += random.Random(42).sample(sorted(set(all_codes) - set(codes)), args.count - len(codes))
        codes.sort()
    frozen = pickle.dumps((names, items), protocol=pickle.HIGHEST_PROTOCOL)
    strategies = [key for key, _, _ in items]
    if not codes:
        raise ValueError("没有可验证的本地股票")
    if set(strategies) != set(service._STRATEGY_NAME_MAP):
        raise RuntimeError("策略注册不完整，不能验收全策略结果")
    data_dir = service.csv_manager.data_dir
    paths = _input_paths(codes, data_dir)
    before = content_manifest(paths)
    _write_json(args.output / "input-manifest.json", before)
    _write_json(args.output / "resolved-config.json", {
        "date": str(args.date), "codes": codes, "history_rows": service.DEFAULT_STRATEGY_SCAN_ROWS,
        "names": {code: names.get(code) for code in codes},
        "strategies": [{"key": key, "name": name, "params": getattr(item, "params", {})}
                       for key, name, item in items],
        "frozen_runtime_sha256": hashlib.sha256(frozen).hexdigest(),
    })
    report = {"date": str(args.date), "count": len(codes), "codes": codes,
              "strategies": strategies, "workers": args.workers, "batch_size": args.batch_size,
              "python": sys.version, "executable": sys.executable, "input_sha256": before["sha256"],
              "pandas": service.pd.__version__,
              "frozen_runtime_sha256": hashlib.sha256(frozen).hexdigest(), "modes": {},
              "verification_scope": "只读计算等价，不代表桌面发布或 MCP 验收"}
    results = {}
    try:
        for mode in ("serial", "process"):
            frozen_names, frozen_items = pickle.loads(frozen)
            started = time.perf_counter()
            rows = []
            for row in iter_scan_results(codes, frozen_names, frozen_items, str(args.date),
                                         backend=mode, workers=args.workers, batch_size=args.batch_size,
                                         data_dir=data_dir, timeout_seconds=args.timeout_seconds):
                rows.append(row)
                if len(rows) % 256 == 0 or len(rows) == len(codes):
                    print(f"{mode}: {len(rows)}/{len(codes)} {time.perf_counter() - started:.2f}s", flush=True)
            elapsed = time.perf_counter() - started
            rows.sort(key=lambda row: row["code"])
            results[mode] = rows
            _write_json(args.output / f"{mode}-results.json", rows)
            report["modes"][mode] = {"seconds": elapsed,
                                     "coverage": validate_coverage(rows, codes, strategies, str(args.date))}
            after = content_manifest(paths)
            _write_json(args.output / f"{mode}-manifest.json", after)
            if after != before:
                raise RuntimeError(f"{mode} 验证期间行情、参数或代码发生变化，结果不可比较")
        comparison = compare_rows(results["serial"], results["process"])
        _write_json(args.output / "comparison.json", comparison)
        report["equivalent"] = comparison["equal"]
        report["result_sha256"] = comparison["actual_sha256"]
        report["inputs_unchanged"] = True
        if args.legacy_results:
            legacy_report_path = args.legacy_results.with_name("report.json")
            if not legacy_report_path.exists():
                raise ValueError("旧基线缺少 report.json，无法核对目标日期")
            legacy_report = json.loads(legacy_report_path.read_text(encoding="utf-8"))
            if legacy_report.get("date") != str(args.date):
                raise ValueError("旧基线目标日期不同，禁止混作同日修错比较")
            old = json.loads(args.legacy_results.read_text(encoding="utf-8"))
            if not isinstance(old, list):
                raise ValueError("legacy-results 必须为旧 benchmark 的逐股 results.json 数组")
            old = [row for row in old if row.get("code") in set(codes)]
            legacy = compare_legacy_rows(old, results["serial"])
            _write_json(args.output / "legacy-comparison.json", legacy)
            report["legacy"] = {key: legacy[key] for key in (
                "equal_on_legacy_fields", "legacy_outcome_coverage", "requires_review", "signal_changes")}
        report["accepted_compute_equivalence"] = report["equivalent"] and all(
            item["coverage"]["successful"] for item in report["modes"].values())
        report["speedup"] = report["modes"]["serial"]["seconds"] / report["modes"]["process"]["seconds"]
    except Exception as exc:
        report["accepted_compute_equivalence"] = False
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        _write_json(args.output / "report.json", report)
    print(canonical({key: value for key, value in report.items() if key not in ("codes", "modes")}), flush=True)
    return 0 if report["accepted_compute_equivalence"] else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
