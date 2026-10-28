"""Freeze and run separate offline contract acceptance without existing test data."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
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


def install_guards():
    keep = {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATH", "PATHEXT"}
    for key in list(os.environ):
        if key.upper() not in keep:
            del os.environ[key]

    def reject(reason):
        VIOLATIONS.append(reason)
        raise RuntimeError(reason)

    def audit(event, args):
        if event == "socket.connect" and sys._getframe(1).f_code is getattr(socket.socketpair, "__code__", None):
            return
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            reject("Network forbidden in independent acceptance")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            if path.name.lower().startswith(".env"):
                reject("Environment-file access forbidden")
            if any(part.lower() in {"evaluator_private", "held_out", "held-out"} for part in path.parts):
                reject("Private evaluation access forbidden")
            if any(path.is_relative_to(ROOT / folder) for folder in ("tests", "scripts", "data")):
                reject("Existing tests, fixtures, scripts and data forbidden")
    sys.addaudithook(audit)
    return reject


def hashes():
    paths = [p for p in (ROOT / "app").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    paths += [ROOT / name for name in ("AGENTS.md", "PROJECT_SPEC.md", "AIRTABLE_SCHEMA.md",
                                      "requirements.txt", "requirements-dev.txt")]
    paths += list(HERE.glob("*.py")) + [HERE / "DESIGN.md"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.record):
        parser.error("Use letters, digits, underscores and hyphens only")
    reject = install_guards()
    before = hashes()
    with (HERE / (args.record + ".baseline.json")).open("x", encoding="utf-8") as output:
        json.dump(before, output, indent=2)
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    with (HERE / (args.record + ".console.txt")).open("x", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log), contextlib.ExitStack() as stack:
            for name in ("openai.OpenAI", "openai.AsyncOpenAI"):
                stack.enter_context(patch(name, side_effect=lambda *a, **k: reject("Real SDK construction forbidden")))
            suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py")
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    after = hashes()
    evidence = dict(started_at_utc=started, duration_seconds=time.monotonic() - clock,
                    tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), guard_violations=VIOLATIONS,
                    sources_unchanged=before == after,
                    failed_cases=[(str(test), detail) for test, detail in result.failures + result.errors])
    evidence["exit_code"] = int(not result.wasSuccessful() or bool(VIOLATIONS) or before != after)
    with (HERE / (args.record + ".results.json")).open("x", encoding="utf-8") as output:
        json.dump(evidence, output, indent=2)
    print(json.dumps({key: value for key, value in evidence.items() if key != "failed_cases"}))
    return evidence["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
