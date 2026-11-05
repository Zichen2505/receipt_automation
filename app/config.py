import os
import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_api_key: str = field(repr=False)
    model_api_key: str = field(repr=False)
    model_name: str
    data_dir: Path
    port: int
    airtable_token: str = field(repr=False)
    airtable_base_id: str
    airtable_table_id: str
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 20
    http_wait_timeout_seconds: float = 130.0
    airtable_timeout_seconds: float = 15.0
    extraction_jobs_enabled: bool = False
    extraction_api_key: str = field(default="", repr=False)
    extraction_integration_scope: str = ""
    extraction_max_active_jobs: int = 32
    extraction_concurrency: int = 1
    extraction_shutdown_grace_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.getenv("APP_API_KEY", "")
        if not key.strip() or key == "replace-with-a-long-random-secret":
            raise ValueError("APP_API_KEY must be set to a non-placeholder secret")
        try:
            port = int(os.getenv("PORT", "8000"))
        except ValueError:
            raise ValueError("PORT must be an integer") from None
        if not 1 <= port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        limits = {}
        for name, default in (("MAX_UPLOAD_BYTES", 10 * 1024 * 1024), ("MAX_PDF_PAGES", 20)):
            try:
                value = int(os.getenv(name, str(default)))
            except ValueError:
                raise ValueError(f"{name} must be a positive integer") from None
            if value <= 0:
                raise ValueError(f"{name} must be a positive integer")
            limits[name] = value
        try:
            timeout = float(os.getenv("HTTP_WAIT_TIMEOUT_SECONDS", "130"))
        except ValueError:
            raise ValueError("HTTP_WAIT_TIMEOUT_SECONDS must be a finite positive number") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("HTTP_WAIT_TIMEOUT_SECONDS must be a finite positive number")
        try:
            airtable_timeout = float(os.getenv("AIRTABLE_TIMEOUT_SECONDS", "15"))
        except ValueError:
            raise ValueError("AIRTABLE_TIMEOUT_SECONDS must be a finite positive number") from None
        if not math.isfinite(airtable_timeout) or airtable_timeout <= 0:
            raise ValueError("AIRTABLE_TIMEOUT_SECONDS must be a finite positive number")
        enabled = os.getenv("EXTRACTION_JOBS_ENABLED", "false").lower()
        if enabled not in {"true", "false"}:
            raise ValueError("EXTRACTION_JOBS_ENABLED must be true or false")
        job_options = {}
        if enabled == "true":
            import re
            extraction_key = os.getenv("EXTRACTION_API_KEY", "")
            scope = os.getenv("EXTRACTION_INTEGRATION_SCOPE", "")
            if (not extraction_key.strip() or extraction_key.startswith("replace-")
                    or extraction_key == key):
                raise ValueError("EXTRACTION_API_KEY must be a dedicated non-placeholder secret")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", scope):
                raise ValueError("EXTRACTION_INTEGRATION_SCOPE must be a stable integration identifier")
            if not os.getenv("MODEL_API_KEY", "").strip() or not os.getenv("MODEL_NAME", "").strip():
                raise ValueError("Enabled extraction jobs require MODEL_API_KEY and MODEL_NAME")
            for name, default in (("EXTRACTION_MAX_ACTIVE_JOBS", 32), ("EXTRACTION_CONCURRENCY", 1)):
                try:
                    value = int(os.getenv(name, str(default)))
                except ValueError:
                    raise ValueError(f"{name} must be a positive integer") from None
                if value <= 0:
                    raise ValueError(f"{name} must be a positive integer")
                job_options[name] = value
            if job_options["EXTRACTION_CONCURRENCY"] > job_options["EXTRACTION_MAX_ACTIVE_JOBS"]:
                raise ValueError("EXTRACTION_CONCURRENCY must not exceed EXTRACTION_MAX_ACTIVE_JOBS")
            try:
                grace = float(os.getenv("EXTRACTION_SHUTDOWN_GRACE_SECONDS", "10"))
            except ValueError:
                raise ValueError("EXTRACTION_SHUTDOWN_GRACE_SECONDS must be finite and positive") from None
            if not math.isfinite(grace) or grace <= 0:
                raise ValueError("EXTRACTION_SHUTDOWN_GRACE_SECONDS must be finite and positive")
        return cls(key, os.getenv("MODEL_API_KEY", ""), os.getenv("MODEL_NAME", ""),
                   Path(os.getenv("DATA_DIR", "./data")).resolve(), port,
                   os.getenv("AIRTABLE_TOKEN", ""), os.getenv("AIRTABLE_BASE_ID", ""),
                   os.getenv("AIRTABLE_TABLE_ID", ""), limits["MAX_UPLOAD_BYTES"],
                   limits["MAX_PDF_PAGES"], timeout, airtable_timeout,
                   extraction_jobs_enabled=enabled == "true",
                   **({"extraction_api_key": extraction_key, "extraction_integration_scope": scope,
                       "extraction_max_active_jobs": job_options["EXTRACTION_MAX_ACTIVE_JOBS"],
                       "extraction_concurrency": job_options["EXTRACTION_CONCURRENCY"],
                       "extraction_shutdown_grace_seconds": grace} if enabled == "true" else {}))
