import asyncio
from contextlib import asynccontextmanager
from tempfile import TemporaryFile

from fastapi import FastAPI

from app.api.routes import health, receipts
from app.config import Settings
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
    service = ReceiptService(settings.data_dir)
    await service.start()
    app.state.receipt_service = service
    yield


app = FastAPI(title="Receipt Agent", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(receipts.router)


def run() -> None:
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(app, host="0.0.0.0", port=settings.port, workers=1)


if __name__ == "__main__":
    run()
