import asyncio
from contextlib import asynccontextmanager
from tempfile import TemporaryFile

from fastapi import FastAPI

from app.api.routes import health, receipts
from app.api.uploads import UploadBodyLimitMiddleware
from app.config import Settings
from app.integrations.airtable import AirtableClient
from app.services.receipt_service import ReceiptService


def prepare_data_dir(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryFile(dir=settings.data_dir) as probe:
        probe.write(b"startup-check")
        probe.flush()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    await asyncio.to_thread(prepare_data_dir, settings)
    app.state.settings = settings
    service = ReceiptService(settings.data_dir, airtable=AirtableClient(
        token=settings.airtable_token, base_id=settings.airtable_base_id,
        table_id=settings.airtable_table_id, timeout_seconds=settings.airtable_timeout_seconds))
    await service.start()
    app.state.receipt_service = service
    app.state.http_tasks = set()
    try:
        yield
    finally:
        # Timed-out/disconnected requests retain ownership through graceful shutdown.
        await asyncio.gather(*tuple(app.state.http_tasks), return_exceptions=True)


app = FastAPI(title="Receipt Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(UploadBodyLimitMiddleware)
app.include_router(health.router)
app.include_router(receipts.router)


def run() -> None:
    import argparse
    from pathlib import Path
    from dotenv import load_dotenv
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the single-process receipt API")
    parser.add_argument("--env-file", type=Path, help="Explicit local dotenv file; existing environment wins")
    args = parser.parse_args()
    if args.env_file is not None:
        if not args.env_file.is_file():
            parser.error("The requested environment file does not exist")
        load_dotenv(args.env_file, override=False, interpolate=False)
    settings = Settings.from_env()
    uvicorn.run(app, host="0.0.0.0", port=settings.port, workers=1)


if __name__ == "__main__":
    run()
