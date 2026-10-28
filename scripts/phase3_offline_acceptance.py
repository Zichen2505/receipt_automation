"""Offline acceptance evidence only: inject previous real output, never call a model."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.schemas.receipt import ReceiptData
from app.services.receipt_service import ReceiptService
from app.storage.repository import get_record

ROOT = Path(__file__).resolve().parents[1]


async def run() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    directory = ROOT / "data/phase3" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    originals = {case: (ROOT / f"tests/fixtures/development/pdfs/{case}.pdf").read_bytes() for case in "ABCDF"}
    by_hash = {hashlib.sha256(pdf).hexdigest(): case for case, pdf in originals.items()}
    calls = []

    async def test_substitute(pdf: bytes, filename: str) -> ReceiptData:
        case = by_hash[hashlib.sha256(pdf).hexdigest()]
        calls.append(case)
        history = ROOT / ("data/phase2/20261023T222741Z_0d6db5ab" if case == "A"
                          else f"data/phase2b/20261023T224454Z_695f2d59/{case}")
        return ReceiptData.model_validate_json((history / "raw_output.txt").read_text(encoding="utf-8"))

    service = ReceiptService(directory / "local-store", extractor=test_substitute)
    results = []
    for case, pdf in originals.items():
        response = await service.process_receipt(pdf, case + ".pdf")
        record = await asyncio.to_thread(get_record, response.receipt_id, db_path=service.db_path)
        expected = json.loads((ROOT / f"tests/fixtures/development/expected/{case}.json").read_text(encoding="utf-8"))
        assert response.data.model_dump(mode="json") == expected["data"]
        assert response.status == ("needs_review" if case == "F" else "saved")
        assert (service.data_dir / record.original_pdf_ref).read_bytes() == pdf
        repeated = await service.process_receipt(pdf, "renamed.pdf")
        assert repeated.receipt_id == response.receipt_id
        results.append({"case_id": case, "record": record.model_dump(mode="json"),
                        "all_data_fields_match_expected": True, "duplicate_id_reused": True})
    assert calls == list("ABCDF")
    summary = {"phase": "3", "verification_kind": "offline workflow using prior real output as test substitute",
               "new_model_requests": 0, "substitute_calls": calls,
               "data_dir": str(service.data_dir.relative_to(ROOT)), "results": results}
    (directory / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact_dir": str(directory.relative_to(ROOT)), "new_model_requests": 0,
                      "statuses": {entry["case_id"]: entry["record"]["response"]["status"] for entry in results}}))


if __name__ == "__main__":
    asyncio.run(run())
