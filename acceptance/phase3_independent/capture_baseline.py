"""Capture an exclusive source baseline without inspecting secrets or fixtures."""

import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FROZEN = sorted(
    [p for p in (ROOT / "app").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    + [ROOT / name for name in (
        "AGENTS.md", "PROJECT_SPEC.md", "AIRTABLE_SCHEMA.md",
        "requirements.txt", "requirements-dev.txt",
    )]
)


def main():
    commands = []
    for args in (["git", "rev-parse", "HEAD"], ["git", "status", "--short"]):
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        commands.append({"command": args, "exit_code": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
    record = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "git": commands,
        "git_blocker": "No Git repository; commit and pre-existing changes unavailable."
        if any(c["exit_code"] for c in commands) else None,
        "sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in FROZEN},
        "tasks_before_sha256": hashlib.sha256((ROOT / "TASKS.md").read_bytes()).hexdigest(),
        "workspace_root_entries": sorted(p.name for p in ROOT.iterdir()),
    }
    with (HERE / "baseline.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print(f"Captured {len(FROZEN)} frozen files; Git baseline available: {not record['git_blocker']}")


if __name__ == "__main__":
    main()
