"""Offline comparison of stored evidence; Decimal values and spelling reported separately."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from app.schemas.receipt import ReceiptData
from scripts.phase2_compare_a import compare_fields
from scripts.phase2_probe import PROJECT_ROOT, write_json

NUMERIC_FIELDS = {"total", "subtotal", "tax", "tip", "discount", "quantity", "unit_price", "amount"}
MONEY_FIELDS = NUMERIC_FIELDS - {"quantity"}


def decimal_comparison(actual: dict, expected: dict) -> dict:
    fields = compare_fields(actual, expected)
    for field in fields:
        field["value_matched"] = field["matched"]
        field["format_only"] = False
        leaf = field["field"].rsplit(".", 1)[-1]
        field["numeric"] = leaf in NUMERIC_FIELDS
        field["money"] = leaf in MONEY_FIELDS
        if field["numeric"] and isinstance(field["actual"], str) and isinstance(field["expected"], str):
            try:
                left, right = Decimal(field["actual"]), Decimal(field["expected"])
                field["value_matched"] = left.is_finite() and right.is_finite() and left == right
                field["format_only"] = field["value_matched"] and not field["matched"]
            except InvalidOperation:
                field["value_matched"] = False
    return {"field_count": len(fields), "fields": fields,
            "exact_difference_count": sum(not field["matched"] for field in fields),
            "value_differences": [field for field in fields if not field["value_matched"]],
            "format_only_differences": [field for field in fields if field["format_only"]],
            "amount_errors": [field for field in fields if field["money"] and not field["value_matched"]]}


def compare_case(case_id: str, case_dir: Path) -> dict:
    metadata = json.loads((case_dir / "extraction_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("outcome") != "succeeded":
        return {"case_id": case_id, "outcome": "not_compared", "reason": "extraction failed"}
    actual_bytes = (case_dir / "actual.json").read_bytes()
    if hashlib.sha256(actual_bytes).hexdigest() != metadata["output_sha256"]:
        raise ValueError("Actual output changed after extraction")
    actual = json.loads(actual_bytes)
    ReceiptData.model_validate(actual)
    # Only this offline step reads the corresponding answer, after checking stored actual evidence.
    expected_path = PROJECT_ROOT / "tests/fixtures/development/expected" / f"{case_id}.json"
    expected_bytes = expected_path.read_bytes()
    wrapper = json.loads(expected_bytes.decode("utf-8-sig"))
    result = decimal_comparison(actual, wrapper["data"])
    result.update(case_id=case_id, outcome="compared", compared_at=datetime.now(timezone.utc).isoformat(),
                  extraction_completed_at=metadata["completed_at"], actual_sha256=metadata["output_sha256"],
                  expected_sha256=hashlib.sha256(expected_bytes).hexdigest(),
                  pdf_sha256=metadata["pdf_sha256"], usage=metadata["usage"],
                  elapsed_seconds=metadata["elapsed_seconds"], expected_page_count=wrapper["page_count"],
                  item_count=len(actual["items"]) if actual["items"] is not None else None,
                  expected_item_count=len(wrapper["data"]["items"]) if wrapper["data"]["items"] is not None else None,
                  key_fields={key: actual[key] for key in ("currency", "subtotal", "tax", "tip", "discount", "total")},
                  comparison_policy="Exact strings retained; numeric fields compared with finite Decimal; formatting differences separate",
                  official_scorer_modified=False, business_validation_executed=False, receipt_status_assigned=False)
    write_json(case_dir / "decimal_comparison.json", result)
    return result


def run(run_dir: Path, a_dir: Path) -> dict:
    run_dir, a_dir = run_dir.resolve(), a_dir.resolve()
    if not run_dir.is_relative_to(PROJECT_ROOT / "data/phase2b") or not a_dir.is_relative_to(PROJECT_ROOT / "data/phase2"):
        raise ValueError("Evidence must be inside the authorized phase artifact directories")
    summary = json.loads((run_dir / "extraction_summary.json").read_text(encoding="utf-8"))
    results = [compare_case("A", a_dir)]
    for metadata in summary["cases"]:
        case_id = metadata["case_id"]
        if case_id not in {"B", "C", "D", "F"}:
            raise ValueError("Unauthorized case identifier")
        results.append(compare_case(case_id, run_dir / case_id))
    combined = {"phase": "2B", "a_evidence_reused_not_rerun": str(a_dir.relative_to(PROJECT_ROOT)),
                "results": results, "not_attempted": summary.get("not_attempted", [])}
    write_json(run_dir / "five_sample_summary.json", combined)
    for result in results:
        print(json.dumps({key: result.get(key) for key in
              ("case_id", "outcome", "field_count", "value_differences", "format_only_differences",
               "amount_errors", "item_count", "expected_item_count", "expected_page_count", "key_fields",
               "usage", "elapsed_seconds")}))
    return combined


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--a-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.run_dir, args.a_dir)
