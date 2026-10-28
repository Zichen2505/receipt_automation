"""Reject private runtime files and likely credentials without printing values."""

import json
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
    names = [name for name in names if name]
    # Read locally only for comparison; never print credentials or matching text.
    secrets = []
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"APP_API_KEY", "MODEL_API_KEY", "OPENAI_API_KEY", "AIRTABLE_TOKEN"}:
                value = value.strip().strip("\"'")
                if len(value) >= 8 and not value.startswith(("replace-", "your-")):
                    secrets.append(value.encode())
    problems = []
    for name in names:
        path = PurePosixPath(name)
        private = (
            (path.name.startswith(".env") and path.name != ".env.example")
            or path.suffix.lower() in {".pdf", ".sqlite", ".sqlite3", ".db", ".pyc"}
            or (name.startswith("data/") and name != "data/.gitkeep")
            or (name.startswith("tests/fixtures/development/") and path.name != ".gitkeep")
            or any(part in {"evaluator_private", "held_out", "held-out", "first-run-source"} for part in path.parts)
            or (name.startswith("acceptance/") and (path.suffix in {".json", ".txt"} or path.name == "REPORT.md"))
        )
        content = git("show", ":" + name)
        credential = any(value in content for value in secrets) or bool(re.search(
            rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)",
            content))
        if private or credential:
            problems.append({"path": name, "reason": "private file" if private else "credential match"})
    print(json.dumps({"staged_files": len(names), "problems": problems, "passed": not problems}))
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
