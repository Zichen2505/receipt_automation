"""Verify frozen sources, retained first-run code and unchanged assertions."""

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def assertions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [ast.dump(node, include_attributes=False) for node in ast.walk(tree)
            if isinstance(node, ast.Assert) or (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("assert"))]


def main():
    baseline = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))
    first = json.loads((HERE / "first-run.results.json").read_text(encoding="utf-8"))
    corrected = json.loads((HERE / "resource-fix-run.results.json").read_text(encoding="utf-8"))
    original_source_verified = all(
        hashlib.sha256((HERE / "first-run-source" / name).read_bytes()).hexdigest() == digest
        for name, digest in first["test_source_before_sha256"].items())
    assertion_comparison = {
        name: assertions(HERE / "first-run-source" / name) == assertions(HERE / name)
        for name in first["test_source_before_sha256"] if name.startswith("test_")}
    frozen_now = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in baseline["sha256"]}
    case_ids_unchanged = [c["id"] for c in first["cases"]] == [c["id"] for c in corrected["cases"]]
    record = {
        "frozen_file_count": len(frozen_now),
        "frozen_files_unchanged": frozen_now == baseline["sha256"],
        "first_run_source_verified": original_source_verified,
        "assertions_unchanged": assertion_comparison,
        "same_90_case_ids_in_both_runs": case_ids_unchanged,
        "first_run_counts": {key: first[key] for key in ("tests_run", "passed", "failures", "errors", "skipped")},
        "resource_fix_run_counts": {key: corrected[key] for key in ("tests_run", "passed", "failures", "errors", "skipped")},
        "cases_by_class": dict(Counter(c["id"].rsplit(".", 1)[0] for c in corrected["cases"])),
        "evidence_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                            for name in ("baseline.json", "DESIGN.md", "first-run.console.txt",
                                         "first-run.results.json", "harness-diagnosis.json",
                                         "resource-fix-run.console.txt", "resource-fix-run.results.json")},
    }
    record["verified"] = (record["frozen_files_unchanged"] and original_source_verified
                          and all(assertion_comparison.values()) and case_ids_unchanged
                          and corrected["exit_code"] == 0)
    with (HERE / "evidence-verification.json").open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")
    print(json.dumps(record, indent=2))
    return int(not record["verified"])


if __name__ == "__main__":
    raise SystemExit(main())
