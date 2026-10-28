"""Run only independent offline acceptance and retain exclusive first-run evidence."""

import asyncio
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
VIOLATIONS = []
SOCKETPAIR_CONNECTIONS = 0


def prohibited(message):
    VIOLATIONS.append(message)
    raise RuntimeError(message)


def install_guards():
    # Keep only operating-system paths needed by Python; never record values.
    keep = {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATH", "PATHEXT"}
    for key in list(os.environ):
        if key.upper() not in keep:
            del os.environ[key]

    def audit(event, args):
        global SOCKETPAIR_CONNECTIONS
        # Windows asyncio wakes its own loop through stdlib's authenticated
        # loopback socketpair. Permit only that exact stdlib call site.
        if event == "socket.connect" and sys._getframe(1).f_code is getattr(socket.socketpair, "__code__", None):
            SOCKETPAIR_CONNECTIONS += 1
            return
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            prohibited("Network access is forbidden in independent acceptance")
        if event != "open" or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        candidate = Path(os.fsdecode(args[0])).absolute()
        lowered = [part.lower() for part in candidate.parts]
        if any(part == ".env" or part.startswith(".env.") for part in lowered):
            prohibited("Environment-file access is forbidden")
        if any(part in {"evaluator_private", "held-out", "held_out"} for part in lowered):
            prohibited("Private evaluation access is forbidden")
        for forbidden in (ROOT / "data", ROOT / "tests", ROOT / "scripts"):
            if candidate.is_relative_to(forbidden):
                prohibited("Existing data, fixtures, scripts and tests are forbidden")

    sys.addaudithook(audit)


def frozen_check(baseline):
    actual = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in baseline["sha256"]}
    source_set = {p.relative_to(ROOT).as_posix() for p in (ROOT / "app").rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts}
    expected_set = {name for name in baseline["sha256"] if name.startswith("app/")}
    return {"unchanged": actual == baseline["sha256"] and source_set == expected_set,
            "sha256": actual, "added_app_files": sorted(source_set - expected_set),
            "removed_app_files": sorted(expected_set - source_set)}


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({"id": test.id(), "outcome": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append({"id": test.id(), "outcome": "failed",
                           "traceback": self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append({"id": test.id(), "outcome": "error",
                           "traceback": self._exc_info_to_string(err, test)})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.cases.append({"id": test.id(), "outcome": "skipped", "reason": reason})


async def worker(mode, directory, receipt_id, payload):
    from app.services.receipt_service import ReceiptService
    from app.storage.repository import get_record
    calls = 0

    async def forbidden_extractor(pdf_bytes, filename):
        nonlocal calls
        calls += 1
        raise AssertionError("Restart must not retry extraction")

    service = ReceiptService(Path(directory), extractor=forbidden_extractor)
    await service.start()
    if mode == "resume":
        response = await service.process_receipt(bytes.fromhex(payload), "restart-context.pdf")
    else:
        response = await service.get_receipt(receipt_id)
    record = await asyncio.to_thread(get_record, receipt_id,
                                    db_path=Path(directory) / "receipts.sqlite3")
    return {"response": response.model_dump(mode="json") if response else None,
            "record": record.model_dump(mode="json") if record else None,
            "extractor_calls": calls, "guard_violations": VIOLATIONS}


def main():
    install_guards()
    with contextlib.ExitStack() as stack:
        for name in ("openai.OpenAI", "openai.AsyncOpenAI"):
            stack.enter_context(patch(name, side_effect=lambda *a, **k: prohibited(
                "Real model SDK client construction is forbidden")))
        if len(sys.argv) > 1 and sys.argv[1] == "--worker":
            print(json.dumps(asyncio.run(worker(*sys.argv[2:]))))
            return int(bool(VIOLATIONS))

        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--record", choices=("first-run", "resource-fix-run"), default="first-run")
        record_name = parser.parse_args().record

        baseline = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))
        before = frozen_check(baseline)
        if not before["unchanged"]:
            raise RuntimeError("Frozen source/contract baseline changed before execution")
        test_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(HERE.glob("*.py"))}
        started = datetime.now(timezone.utc).isoformat()
        clock = time.monotonic()
        # Exclusive creation protects the first result even if the suite crashes.
        with (HERE / f"{record_name}.console.txt").open("x", encoding="utf-8") as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py")
                result = unittest.TextTestRunner(stream=log, verbosity=2,
                                                resultclass=EvidenceResult).run(suite)
        after = frozen_check(baseline)
        after_test_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(HERE.glob("*.py"))}
        exit_code = int(not result.wasSuccessful() or bool(VIOLATIONS)
                        or not after["unchanged"] or test_hashes != after_test_hashes)
        evidence = {
            "command": [".\\.venv\\Scripts\\python", "-B",
                        "acceptance\\phase3_independent\\run.py"] + sys.argv[1:],
            "started_at_utc": started, "duration_seconds": time.monotonic() - clock,
            "exit_code": exit_code, "tests_run": result.testsRun,
            "passed": sum(c["outcome"] == "passed" for c in result.cases),
            "failures": len(result.failures), "errors": len(result.errors),
            "skipped": len(result.skipped), "cases": result.cases,
            "source_before": before, "source_after": after,
            "test_source_before_sha256": test_hashes,
            "test_source_after_sha256": after_test_hashes,
            "guard_violations": VIOLATIONS,
            "stdlib_socketpair_connections": SOCKETPAIR_CONNECTIONS,
            "isolation": "Explicit unittest discovery; no existing tests/plugins/fixtures; "
                         "application environment removed; SDK/network/file guards enabled; "
                         "injected extractors and temporary DATA_DIR only",
        }
        with (HERE / f"{record_name}.results.json").open("x", encoding="utf-8") as output:
            json.dump(evidence, output, indent=2)
            output.write("\n")
        print(json.dumps({key: evidence[key] for key in (
            "tests_run", "passed", "failures", "errors", "skipped", "exit_code",
            "duration_seconds", "guard_violations")}))
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
