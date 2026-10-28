import math
import asyncio
from collections.abc import Awaitable, Callable
import json
from urllib.parse import quote

import httpx

from app.schemas.receipt import ReceiptResponse, SyncResult


def map_receipt_fields(receipt: ReceiptResponse) -> dict[str, str | float | None]:
    """Pure mapping; never contacts Airtable or invents a missing value."""
    if receipt.status != "saved" or not receipt.validation.passed or receipt.data is None:
        raise ValueError("Only saved, validated receipts can be synced")
    data = receipt.data
    amount = float(data.total) if data.total is not None else None
    if amount is not None and not math.isfinite(amount):
        raise ValueError("Amount cannot be represented as a finite JSON number")
    return {
        "Vendor": data.merchant,
        "Date": data.date.isoformat() if data.date else None,
        "Amount": amount,
        "Currency": data.currency,
        "RawJSON": data.model_dump_json(),
        "ReceiptID": receipt.receipt_id,
    }


class AirtableClient:
    """Record-only adapter. No schema mutation, redirects, or automatic retries."""

    def __init__(self, *, token: str, base_id: str, table_id: str,
                 timeout_seconds: float = 15.0, transport=None):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Airtable timeout must be finite and positive")
        self._token = token
        self._base_id = base_id
        self._table_id = table_id
        self._timeout = timeout_seconds
        self._transport = transport

    @property
    def configured(self) -> bool:
        return all(value.strip() for value in (self._token, self._base_id, self._table_id))

    async def sync_receipt(self, receipt: ReceiptResponse, *, allow_create: bool,
                           before_create: Callable[[], Awaitable[None]]) -> SyncResult:
        if receipt.status != "saved" or not receipt.validation.passed or receipt.data is None:
            return SyncResult(status="skipped")
        if not self.configured:
            return SyncResult(status="not_configured")
        uncertain = not allow_create
        try:
            fields = map_receipt_fields(receipt)
            # Escape formula literals independently from URL parameter encoding.
            identifier = receipt.receipt_id.replace("\\", "\\\\").replace("'", "\\'")
            url = ("https://api.airtable.com/v0/" + quote(self._base_id, safe="")
                   + "/" + quote(self._table_id, safe=""))
            async with httpx.AsyncClient(
                headers={"Authorization": "Bearer " + self._token},
                timeout=self._timeout, follow_redirects=False, trust_env=False,
                transport=self._transport,
            ) as client:
                async with asyncio.timeout(self._timeout):
                    response = await client.get(url, params={
                        "filterByFormula": "{ReceiptID}='" + identifier + "'",
                        "maxRecords": 2, "pageSize": 2,
                    })
                response.raise_for_status()
                payload = response.json()
                records = payload["records"]
                if not isinstance(records, list):
                    raise ValueError("Invalid records response")
                if payload.get("offset") or len(records) > 1:
                    return SyncResult(status="unknown")
                if records:
                    record = records[0]
                    if not self._matches(record, fields):
                        return SyncResult(status="unknown")
                    return SyncResult(status="synced", record_id=record["id"])
                if not allow_create:
                    # Absence after an uncertain write is not proof that it cannot commit later.
                    return SyncResult(status="unknown")
                # Commit uncertainty BEFORE dispatch. Storage failure must prevent the write.
                await before_create()
                uncertain = True
                async with asyncio.timeout(self._timeout):
                    response = await client.post(url, json={"records": [{"fields": fields}], "typecast": False})
                if 400 <= response.status_code < 500 and response.status_code != 408:
                    return SyncResult(status="failed")
                response.raise_for_status()
                records = response.json()["records"]
                if not isinstance(records, list) or len(records) != 1 or not self._matches(records[0], fields):
                    return SyncResult(status="unknown")
                return SyncResult(status="synced", record_id=records[0]["id"])
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            # Never echo a response body, URL, token, or exception text.
            return SyncResult(status="unknown" if uncertain else "failed")

    @staticmethod
    def _matches(record: dict, fields: dict) -> bool:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"].startswith("rec"):
            return False
        remote = record.get("fields")
        if not isinstance(remote, dict):
            return False
        return (all(remote.get(key) == fields[key] for key in ("ReceiptID", "Vendor", "Date", "Amount", "Currency"))
                and json.loads(remote.get("RawJSON", "null")) == json.loads(fields["RawJSON"]))
