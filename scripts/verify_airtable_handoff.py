"""Read-only comparison with the pushed prior phase and retained evidence."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PRIOR = "279c9a0ebc3c51e6273deb4ec5a2f30238144ff2"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def assertions(source):
    return [ast.dump(node, include_attributes=False) for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Assert) or (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert"))]


def main():
    paths = git("ls-tree", "-r", "--name-only", PRIOR, "tests", "acceptance/phase3_independent").decode().splitlines()
    unchanged_assertions = all(
        assertions(git("show", PRIOR + ":" + name).decode("utf-8")) == assertions((ROOT / name).read_text(encoding="utf-8"))
        for name in paths if Path(name).name.startswith("test_") and name.endswith(".py"))
    protected = ["AIRTABLE_SCHEMA.md", "app/schemas/receipt.py", "app/services/validation.py",
                 "acceptance/phase3_independent"]
    unchanged_protected = not git("diff", PRIOR, "--", *protected).strip()
    folder = ROOT / "acceptance/phase3_independent"
    evidence = json.loads((folder / "evidence-verification.json").read_text(encoding="utf-8"))
    original_evidence = all(hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
                            for name, digest in evidence["evidence_sha256"].items())
    first = json.loads((folder / "first-run.results.json").read_text(encoding="utf-8"))
    original_sources = all(hashlib.sha256((folder / "first-run-source" / name).read_bytes()).hexdigest() == digest
                           for name, digest in first["test_source_before_sha256"].items())
    report = dict(prior_commit=PRIOR, prior_assertions_unchanged=unchanged_assertions,
                  protected_tracked_files_unchanged=unchanged_protected,
                  retained_original_evidence_unchanged=original_evidence,
                  original_first_run_sources_unchanged=original_sources)
    print(json.dumps(report))
    return int(not all((unchanged_assertions, unchanged_protected, original_evidence, original_sources)))


if __name__ == "__main__":
    raise SystemExit(main())
