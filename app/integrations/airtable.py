import math

from app.contracts import FeatureNotImplementedError
from app.schemas.receipt import ReceiptResponse


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


async def sync_receipt(receipt: ReceiptResponse) -> str:
    raise FeatureNotImplementedError("Remote Airtable writes are not implemented")
