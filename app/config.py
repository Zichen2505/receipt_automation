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
        return cls(key, os.getenv("MODEL_API_KEY", ""), os.getenv("MODEL_NAME", ""),
                   Path(os.getenv("DATA_DIR", "./data")).resolve(), port,
                   os.getenv("AIRTABLE_TOKEN", ""), os.getenv("AIRTABLE_BASE_ID", ""),
                   os.getenv("AIRTABLE_TABLE_ID", ""), limits["MAX_UPLOAD_BYTES"],
                   limits["MAX_PDF_PAGES"], timeout)
