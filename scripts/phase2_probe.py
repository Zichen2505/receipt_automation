"""One text-only API probe. Never load expected answers or log credentials."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from time import perf_counter
import uuid

from dotenv import load_dotenv
from openai import AsyncOpenAI, APIStatusError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def prepare_run() -> Path:
    # The explicit local runner loads .env; importing the app never does.
    load_dotenv(PROJECT_ROOT / ".env", override=False, interpolate=False)
    logging.getLogger("openai").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpx2").setLevel(logging.CRITICAL)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = PROJECT_ROOT / "data" / "phase2" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_error(exc: Exception) -> dict:
    # Do not persist str(exc), response bodies, request headers, or tracebacks.
    result = {"type": type(exc).__name__, "message": "Request failed; raw exception withheld to protect credentials"}
    if isinstance(exc, APIStatusError):
        result["http_status"] = exc.status_code
        code = getattr(exc, "code", None)
        allowed = {"insufficient_quota", "rate_limit_exceeded", "model_not_found", "invalid_api_key", "permission_denied"}
        result["code"] = code if isinstance(code, str) and code in allowed else "unclassified_api_error"
    return result


async def probe(run_dir: Path) -> bool:
    started = perf_counter()
    metadata = {"stage": "text_probe", "started_at": datetime.now(timezone.utc).isoformat(),
                "max_retries": 0, "usage": None, "pdf_attempted": False,
                "expected_read": False, "model": os.getenv("MODEL_NAME", "")}
    try:
        key = os.getenv("MODEL_API_KEY", "")
        model = os.getenv("MODEL_NAME", "")
        if not key.strip() or not model.strip():
            raise ValueError("MODEL_API_KEY and MODEL_NAME are required")
        async with AsyncOpenAI(api_key=key, base_url="https://api.openai.com/v1",
                               max_retries=0, timeout=30.0) as client:
            response = await client.responses.create(
                model=model, input="Reply only with OK.", max_output_tokens=32, store=False,
            )
        metadata.update(response_id=response.id, response_status=response.status,
                        usage=response.usage.model_dump(mode="json") if response.usage else None,
                        output_text=response.output_text)
        if response.status != "completed" or not response.output_text.strip():
            raise ValueError("Text probe did not complete with non-empty output")
        metadata["outcome"] = "succeeded"
    except Exception as exc:
        metadata.update(outcome="failed", error=safe_error(exc))
    metadata["elapsed_seconds"] = round(perf_counter() - started, 6)
    write_json(run_dir / "text_probe.json", metadata)
    print(json.dumps({"outcome": metadata["outcome"], "artifact_dir": str(run_dir.relative_to(PROJECT_ROOT)),
                      "elapsed_seconds": metadata["elapsed_seconds"], "error": metadata.get("error")}, ensure_ascii=True))
    return metadata["outcome"] == "succeeded"


def main() -> None:
    run_dir = prepare_run()
    raise SystemExit(0 if asyncio.run(probe(run_dir)) else 1)


if __name__ == "__main__":
    main()
