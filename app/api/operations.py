"""Retain in-flight service calls when HTTP waiting times out or disconnects."""

import asyncio

from fastapi import HTTPException, Request

from app.contracts import ReceiptStorageError


async def wait_for_operation(request: Request, operation, *, timeout_code: str):
    task = asyncio.create_task(operation)
    tasks = request.app.state.http_tasks
    tasks.add(task)

    def finished(completed):
        tasks.discard(completed)
        if not completed.cancelled():
            # Retrieve exceptions for detached calls without logging private details.
            completed.exception()

    task.add_done_callback(finished)
    try:
        return await asyncio.wait_for(asyncio.shield(task),
                                      timeout=request.app.state.settings.http_wait_timeout_seconds)
    except TimeoutError:
        raise HTTPException(status_code=504, detail={
            "code": timeout_code, "message": "HTTP waiting timed out; the receipt outcome is unknown",
            "outcome": "unknown",
        }) from None
    except ReceiptStorageError:
        raise HTTPException(status_code=503, detail={
            "code": "storage_unavailable", "message": "Local receipt storage is unavailable",
            "outcome": "unknown",
        }) from None
    except Exception:
        raise HTTPException(status_code=500, detail={
            "code": "internal_error", "message": "Receipt operation could not be completed",
            "outcome": "unknown",
        }) from None
