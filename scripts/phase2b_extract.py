"""One sequential request per B/C/D/F PDF; no expected-answer access."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
from time import perf_counter
import uuid

from dotenv import load_dotenv

from app.integrations.extractor import parse_extraction, request_extraction
from scripts.phase2_probe import PROJECT_ROOT, safe_error, write_json

CASES = ("B", "C", "D", "F")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def extract_case(case_id: str, run_dir: Path) -> dict:
    if case_id not in CASES:
        raise ValueError("Only B, C, D, F are authorized")
    case_dir = run_dir / case_id
    case_dir.mkdir(exist_ok=False)
    pdf_path = PROJECT_ROOT / "tests/fixtures/development/pdfs" / f"{case_id}.pdf"
    pdf_bytes = pdf_path.read_bytes()
    metadata = {
        "case_id": case_id, "filename": pdf_path.name, "stage": "pdf_extraction",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": os.getenv("MODEL_NAME", ""), "max_retries": 0,
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "expected_read": False, "usage": None, "outcome": "failed",
        "business_validation_executed": False, "receipt_status_assigned": False,
    }
    write_json(case_dir / "pdf_attempt.json", metadata)
    started = perf_counter()
    try:
        response = await request_extraction(pdf_bytes, pdf_path.name)
        metadata.update(response_id=response.id, response_status=response.status,
                        usage=response.usage.model_dump(mode="json") if response.usage else None)
        raw_path = case_dir / "raw_output.txt"
        raw_path.write_text(response.output_text, encoding="utf-8")
        metadata["raw_output_sha256"] = sha256(raw_path)
        receipt = parse_extraction(response)
        actual_path = case_dir / "actual.json"
        actual_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
        metadata.update(outcome="succeeded", output_sha256=sha256(actual_path))
    except Exception as exc:
        metadata["error"] = safe_error(exc)
    metadata["elapsed_seconds"] = round(perf_counter() - started, 6)
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(case_dir / "extraction_metadata.json", metadata)
    print(json.dumps({key: metadata.get(key) for key in
                     ("case_id", "outcome", "elapsed_seconds", "usage", "error")}), flush=True)
    return metadata


async def run() -> bool:
    load_dotenv(PROJECT_ROOT / ".env", override=False, interpolate=False)
    for name in ("openai", "httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    if not os.getenv("MODEL_API_KEY", "").strip() or not os.getenv("MODEL_NAME", "").strip():
        raise ValueError("MODEL_API_KEY and MODEL_NAME are required")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = PROJECT_ROOT / "data/phase2b" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    sources = ["app/integrations/extractor.py", "app/prompts/extract_receipt.txt",
               "app/schemas/receipt.py", "AIRTABLE_SCHEMA.md"]
    sources += [f"tests/fixtures/development/pdfs/{case}.pdf" for case in ("A", *CASES)]
    write_json(run_dir / "source_hashes.json", {name: sha256(PROJECT_ROOT / name) for name in sources})
    print(json.dumps({"artifact_dir": str(run_dir.relative_to(PROJECT_ROOT))}), flush=True)
    summary = {"phase": "2B", "authorized_cases": list(CASES), "cases": [],
               "text_probe_executed": False, "a_requested": False, "expected_read": False}
    for case_id in CASES:
        metadata = await extract_case(case_id, run_dir)
        summary["cases"].append(metadata)
        write_json(run_dir / "extraction_summary.json", summary)
        # Conservatively stop on any request/parsing failure, including auth/quota/permissions.
        if metadata["outcome"] != "succeeded":
            summary["stopped_after"] = case_id
            summary["not_attempted"] = list(CASES[len(summary["cases"]):])
            write_json(run_dir / "extraction_summary.json", summary)
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
