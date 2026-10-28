"""Extract only development A.pdf after a successful probe; never read expected."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from app.integrations.extractor import parse_extraction, request_extraction
from scripts.phase2_probe import PROJECT_ROOT, safe_error, write_json


async def run(run_dir: Path) -> bool:
    load_dotenv(PROJECT_ROOT / ".env", override=False, interpolate=False)
    for logger_name in ("openai", "httpx", "httpx2"):
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to(PROJECT_ROOT / "data" / "phase2"):
        raise ValueError("Run artifacts must remain inside data/phase2")
    probe = json.loads((run_dir / "text_probe.json").read_text(encoding="utf-8"))
    if probe.get("outcome") != "succeeded" or probe.get("model") != os.getenv("MODEL_NAME"):
        raise ValueError("A successful text probe for the configured model is required")
    # Exclusive marker prevents a rerun from silently issuing another paid PDF request.
    with (run_dir / "pdf_attempt.json").open("x", encoding="utf-8") as marker:
        json.dump({"started_at": datetime.now(timezone.utc).isoformat(), "max_retries": 0}, marker)
    pdf_path = PROJECT_ROOT / "tests" / "fixtures" / "development" / "pdfs" / "A.pdf"
    pdf_bytes = pdf_path.read_bytes()
    metadata = {"stage": "pdf_extraction", "filename": "A.pdf", "model": os.getenv("MODEL_NAME"),
                "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(), "max_retries": 0,
                "usage": None, "expected_read": False, "outcome": "failed"}
    started = perf_counter()
    try:
        response = await request_extraction(pdf_bytes, "A.pdf")
        metadata.update(response_id=response.id, response_status=response.status,
                        usage=response.usage.model_dump(mode="json") if response.usage else None)
        # Save actual output before parsing, and before any separate comparison is allowed.
        (run_dir / "raw_output.txt").write_text(response.output_text, encoding="utf-8")
        receipt = parse_extraction(response)
        (run_dir / "actual.json").write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
        metadata.update(outcome="succeeded", output_sha256=hashlib.sha256((run_dir / "actual.json").read_bytes()).hexdigest())
    except Exception as exc:
        metadata["error"] = safe_error(exc)
    metadata["elapsed_seconds"] = round(perf_counter() - started, 6)
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(run_dir / "extraction_metadata.json", metadata)
    print(json.dumps({"outcome": metadata["outcome"], "elapsed_seconds": metadata["elapsed_seconds"],
                      "usage": metadata["usage"], "error": metadata.get("error")}, ensure_ascii=True))
    return metadata["outcome"] == "succeeded"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run(args.run_dir)) else 1)


if __name__ == "__main__":
    main()
