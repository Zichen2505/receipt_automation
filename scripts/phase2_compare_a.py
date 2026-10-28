"""Offline, field-by-field comparison after actual extraction has been saved."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from app.schemas.receipt import ReceiptData
from scripts.phase2_probe import PROJECT_ROOT, write_json


def compare_fields(actual, expected, path="data") -> list[dict]:
    if isinstance(actual, dict) and isinstance(expected, dict):
        results = []
        for key in sorted(actual.keys() | expected.keys()):
            child = path + "." + key
            if key not in actual or key not in expected:
                results.append({"field": child, "actual_present": key in actual,
                                "expected_present": key in expected, "actual": actual.get(key),
                                "expected": expected.get(key), "matched": False})
            else:
                results.extend(compare_fields(actual[key], expected[key], child))
        return results
    if isinstance(actual, list) and isinstance(expected, list):
        results = [{"field": path + ".length", "actual": len(actual), "expected": len(expected),
                    "matched": len(actual) == len(expected)}]
        for index in range(max(len(actual), len(expected))):
            child = f"{path}[{index}]"
            if index >= len(actual) or index >= len(expected):
                results.append({"field": child, "actual_present": index < len(actual),
                                "expected_present": index < len(expected),
                                "actual": actual[index] if index < len(actual) else None,
                                "expected": expected[index] if index < len(expected) else None,
                                "matched": False})
            else:
                results.extend(compare_fields(actual[index], expected[index], child))
        return results
    return [{"field": path, "actual": actual, "expected": expected,
             "matched": type(actual) is type(expected) and actual == expected}]


def compare(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to(PROJECT_ROOT / "data" / "phase2"):
        raise ValueError("Run artifacts must remain inside data/phase2")
    metadata = json.loads((run_dir / "extraction_metadata.json").read_text(encoding="utf-8"))
    actual_path = run_dir / "actual.json"
    if metadata.get("outcome") != "succeeded":
        raise ValueError("Successful extraction is required before reading expected")
    actual_bytes = actual_path.read_bytes()
    if hashlib.sha256(actual_bytes).hexdigest() != metadata["output_sha256"]:
        raise ValueError("Actual output changed after extraction")
    actual = json.loads(actual_bytes)
    ReceiptData.model_validate(actual)
    # This is the first expected-answer read in the live workflow, after persisted actual output.
    expected_path = PROJECT_ROOT / "tests" / "fixtures" / "development" / "expected" / "A.json"
    expected_bytes = expected_path.read_bytes()
    expected = json.loads(expected_bytes.decode("utf-8-sig"))["data"]
    fields = compare_fields(actual, expected)
    differences = [field for field in fields if not field["matched"]]
    result = {"case_id": "A", "compared_at": datetime.now(timezone.utc).isoformat(),
              "extraction_completed_at": metadata["completed_at"],
              "actual_sha256": metadata["output_sha256"],
              "expected_sha256": hashlib.sha256(expected_bytes).hexdigest(),
              "comparison": "exact JSON values including decimal strings; no normalization",
              "field_count": len(fields), "matched_fields": len(fields) - len(differences),
              "difference_count": len(differences), "fields": fields, "differences": differences,
              "business_validation_executed": False, "receipt_saved_status_assigned": False}
    write_json(run_dir / "comparison.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    result = compare(parser.parse_args().run_dir)
    print(json.dumps({key: result[key] for key in ("case_id", "field_count", "matched_fields", "difference_count", "differences")}))


if __name__ == "__main__":
    main()
