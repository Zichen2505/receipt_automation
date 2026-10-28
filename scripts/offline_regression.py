"""Run regressions offline, saving a fresh local report and guarding child processes."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def protected_hashes():
    paths = [ROOT / "AIRTABLE_SCHEMA.md"]
    for folder in (ROOT / "tests/fixtures/development/pdfs", ROOT / "tests/fixtures/development/expected"):
        paths.extend(p for p in folder.glob("*") if p.is_file())
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    os.chdir(ROOT)
    for name in ("APP_API_KEY", "MODEL_API_KEY", "MODEL_NAME", "OPENAI_API_KEY", "AIRTABLE_TOKEN",
                 "AIRTABLE_BASE_ID", "AIRTABLE_TABLE_ID", "DATA_DIR", "PORT", "MAX_UPLOAD_BYTES",
                 "MAX_PDF_PAGES", "HTTP_WAIT_TIMEOUT_SECONDS"):
        os.environ.pop(name, None)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    evidence = ROOT / "data" / "http_api" / run_id
    evidence.mkdir(parents=True)
    before = protected_hashes()
    os.environ["RECEIPT_OFFLINE_AUDIT_LOG"] = str(evidence / "guard-violations.jsonl")
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    arguments = sys.argv[1:] or ["tests"]
    with tempfile.TemporaryDirectory(prefix="receipt-offline-guard-") as directory:
        # Python imports this before -m pytest and in inherited child interpreters.
        Path(directory, "sitecustomize.py").write_text(
            "from scripts.offline_guard import install\ninstall()\n", encoding="utf-8")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = directory + os.pathsep + str(ROOT)
        command = [sys.executable, "-B", "-m", "pytest", "-q", *arguments,
                   "--junitxml=" + str(evidence / "regression.xml")]
        with (evidence / "console.txt").open("x", encoding="utf-8") as log:
            result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
    after = protected_hashes()
    counts = {}
    report = evidence / "regression.xml"
    if report.exists():
        tree = ET.parse(report)
        counts = {key: sum(int(suite.get(key, "0")) for suite in tree.findall(".//testsuite"))
                  for key in ("tests", "failures", "errors", "skipped")}
    violated = (evidence / "guard-violations.jsonl").exists()
    record = {"command": command, "exit_code": result.returncode, "counts": counts,
              "protected_inputs_unchanged": before == after, "protected_sha256": after,
              "guard_violations": violated, "evidence": evidence.relative_to(ROOT).as_posix()}
    with (evidence / "result.json").open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")
    print(json.dumps({key: value for key, value in record.items() if key != "protected_sha256"}))
    return int(result.returncode != 0 or before != after or violated)


if __name__ == "__main__":
    raise SystemExit(main())
