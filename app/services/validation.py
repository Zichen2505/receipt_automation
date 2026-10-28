"""Deterministic exact Decimal checks; unknown values never become zero."""
from decimal import Decimal, localcontext

from app.schemas.receipt import ReceiptData, ValidationIssue, ValidationResult


def validate_receipt(data: ReceiptData) -> ValidationResult:
    issues = []

    def issue(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, field=field, message=message))

    for field in ("merchant", "date", "currency", "total"):
        value = getattr(data, field)
        if value is None or (isinstance(value, str) and not value.strip()):
            issue("missing_" + field, field, f"Required field {field} is missing")
    values = [getattr(data, name) for name in ("total", "subtotal", "tax", "tip", "discount")]
    values += [value for item in data.items or [] for value in (item.quantity, item.unit_price, item.amount)]
    # Precision scales with inputs instead of silently rounding long Decimal products/sums.
    with localcontext() as context:
        context.prec = max(64, sum(len(v.as_tuple().digits) + abs(v.as_tuple().exponent)
                                   for v in values if v is not None) + 16)
        money = [(name, getattr(data, name)) for name in ("total", "subtotal", "tax", "tip", "discount")]
        money += [(f"items[{i}].{name}", getattr(item, name)) for i, item in enumerate(data.items or [])
                  for name in ("unit_price", "amount")]
        for field, value in money:
            if value is not None and value % Decimal("0.01") != 0:
                issue("invalid_amount_precision", field, "Amount must be an exact multiple of 0.01")
        if data.discount is not None and data.discount < 0:
            issue("invalid_discount", "discount", "Discount must be a positive magnitude or zero")
        for i, item in enumerate(data.items or []):
            if all(value is not None for value in (item.quantity, item.unit_price, item.amount)):
                if item.quantity * item.unit_price != item.amount:
                    issue("item_amount_mismatch", f"items[{i}].amount", "Quantity times unit price differs from line amount")
        if data.items and data.subtotal is not None and all(item.amount is not None for item in data.items):
            if sum((item.amount for item in data.items), Decimal(0)) != data.subtotal:
                issue("subtotal_mismatch", "subtotal", "Sum of item amounts differs from subtotal")
        components = (data.subtotal, data.discount, data.tax, data.tip, data.total)
        if all(value is not None for value in components):
            if data.subtotal - data.discount + data.tax + data.tip != data.total:
                issue("total_mismatch", "total", "Subtotal minus discount plus tax and tip differs from printed total")
    return ValidationResult(passed=not issues, issues=issues)
