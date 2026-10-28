"""Direct PDF extraction through the official OpenAI Responses SDK."""
import asyncio
import base64
import os
from pathlib import Path
from time import perf_counter

from openai import AsyncOpenAI
from openai.types.responses import Response

from app.schemas.receipt import ExtractionMetadata, NormalizationEvent, ReceiptData


def normalize_receipt_data(data: ReceiptData) -> tuple[ReceiptData, list[NormalizationEvent]]:
    """Normalize only the explicit discount amount; never mutate caller data."""
    original = data.discount
    normalized = original.copy_abs() if original is not None else None
    reason = "unknown_discount_preserved" if original is None else (
        "negative_discount_converted_to_positive_magnitude" if original.is_signed()
        else "discount_already_positive_magnitude"
    )
    return data.model_copy(update={"discount": normalized}), [NormalizationEvent(
        original_value=original, normalized_value=normalized, reason=reason,
    )]


def receipt_output_schema() -> dict:
    """Derive strict model output fields from the single shared schema source."""
    schema = ReceiptData.model_json_schema(mode="serialization")

    def require_all(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            node.pop("default", None)
            for value in node.values():
                require_all(value)
        elif isinstance(node, list):
            for value in node:
                require_all(value)

    require_all(schema)
    return schema


async def request_extraction(pdf_bytes: bytes, filename: str) -> Response:
    """One API request, no retry or expected-answer access; no persistence claim."""
    key = os.getenv("MODEL_API_KEY", "")
    model = os.getenv("MODEL_NAME", "")
    if not key.strip() or not model.strip():
        raise ValueError("MODEL_API_KEY and MODEL_NAME are required for extraction")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Input must contain a PDF header")
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "extract_receipt.txt"
    prompt = await asyncio.to_thread(prompt_path.read_text, encoding="utf-8")
    file_data = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
    async with AsyncOpenAI(api_key=key, base_url="https://api.openai.com/v1",
                           max_retries=0, timeout=120.0) as client:
        return await client.responses.create(
            model=model, store=False, max_output_tokens=4096,
            instructions=prompt,
            input=[{"role": "user", "content": [
                {"type": "input_file", "filename": Path(filename).name, "file_data": file_data},
                {"type": "input_text", "text": "Extract this receipt."},
            ]}],
            text={"format": {"type": "json_schema", "name": "ReceiptData",
                             "strict": True, "schema": receipt_output_schema()}},
        )


def parse_extraction(response: Response) -> ReceiptData:
    return parse_extraction_with_metadata(response)[0]


def parse_extraction_with_metadata(response: Response) -> tuple[ReceiptData, ExtractionMetadata]:
    if response.status != "completed" or not response.output_text.strip():
        raise ValueError("Extraction did not complete with structured output")
    raw = ReceiptData.model_validate_json(response.output_text)
    data, events = normalize_receipt_data(raw)
    usage = getattr(response, "usage", None)
    return data, ExtractionMetadata(
        raw_output=response.output_text, normalizations=events,
        response_id=getattr(response, "id", None), model=getattr(response, "model", None),
        usage=usage.model_dump(mode="json") if usage else None,
    )


async def extract_with_metadata(pdf_bytes: bytes, filename: str) -> tuple[ReceiptData, ExtractionMetadata]:
    started = perf_counter()
    data, metadata = parse_extraction_with_metadata(await request_extraction(pdf_bytes, filename))
    metadata.elapsed_seconds = perf_counter() - started
    return data, metadata


async def extract(pdf_bytes: bytes, filename: str) -> ReceiptData:
    return (await extract_with_metadata(pdf_bytes, filename))[0]
