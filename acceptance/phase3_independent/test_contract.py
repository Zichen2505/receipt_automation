"""New synthetic cases derived solely from the frozen business contract."""

from decimal import Decimal, localcontext
import json
from types import SimpleNamespace
import unittest

from app.integrations.extractor import normalize_receipt_data, parse_extraction_with_metadata
from app.schemas.receipt import ReceiptData, ReceiptItem
from app.services.validation import validate_receipt


def data(**changes):
    values = {"merchant": "Independent Cedar Studio", "date": "2026-08-19",
              "receipt_number": "SYNTHETIC-83", "currency": "CAD", "total": "83.29"}
    values.update(changes)
    return ReceiptData.model_validate(values)


def complete(**changes):
    # 4.25 * 12.00 = 51.00; 51.00 + 34.80 = 85.80;
    # 85.80 - 6.40 + 2.89 + 1.00 = 83.29.
    values = {"subtotal": "85.80", "discount": "6.40", "tax": "2.89", "tip": "1.00",
              "items": [{"description": "Synthetic weighted service", "quantity": "4.25",
                         "unit_price": "12.00", "amount": "51.00"},
                        {"description": "Synthetic fixed service", "quantity": "3",
                         "unit_price": "11.60", "amount": "34.80"}]}
    values.update(changes)
    return data(**values)


class ValidationContract(unittest.TestCase):
    def check(self, value, expected):
        before = value.model_dump_json()
        result = validate_receipt(value)
        self.assertEqual({(i.code, i.field) for i in result.issues}, set(expected))
        self.assertEqual(result.passed, not expected)
        self.assertTrue(all(i.message.strip() for i in result.issues))
        self.assertEqual(value.model_dump_json(), before)

    def test_complete_exact_arithmetic(self):
        self.check(complete(), [])

    def test_all_required_omitted(self):
        self.check(ReceiptData(), [("missing_" + f, f)
                                  for f in ("merchant", "date", "currency", "total")])

    def test_zero_total_and_explicit_zero_components(self):
        value = data(total="0", subtotal="0.0000", discount="0", tax="0", tip="0", items=[])
        self.check(value, [])
        self.assertEqual(value.total, Decimal("0"))

    def test_optional_unknowns_preserve_null_and_decimal_strings(self):
        value = data()
        self.check(value, [])
        dumped = value.model_dump(mode="json")
        self.assertEqual(dumped["total"], "83.29")
        for field in ("subtotal", "tax", "tip", "discount", "items"):
            self.assertIsNone(dumped[field])
        self.assertEqual(dumped["date"], "2026-08-19")

    def test_all_three_equations_report_independent_conflicts(self):
        value = complete(total="83.31", subtotal="85.81", items=[
            {"quantity": "4.25", "unit_price": "12.00", "amount": "51.01"},
            {"quantity": "3", "unit_price": "11.60", "amount": "34.81"}])
        self.check(value, [("item_amount_mismatch", "items[0].amount"),
                           ("item_amount_mismatch", "items[1].amount"),
                           ("subtotal_mismatch", "subtotal"), ("total_mismatch", "total")])

    def test_fractional_quantity_not_restricted_to_cents(self):
        self.check(data(items=[{"quantity": "0.000125", "unit_price": "80.00", "amount": "0.01"}]), [])

    def test_no_float_tolerance_for_line_amount(self):
        self.check(data(items=[{"quantity": "0.3333333333333333333333333333333333333333",
                               "unit_price": "3.00", "amount": "1.00"}]),
                   [("item_amount_mismatch", "items[0].amount")])

    def test_very_large_values_under_small_ambient_context(self):
        value = data(total="1234567890123456789012345678901234567890.12",
                     subtotal="1234567890123456789012345678901234567890.12",
                     discount="0.00", tax="0.00", tip="0.00", items=[
                         {"quantity": "1", "unit_price": "1234567890123456789012345678901234567890.12",
                          "amount": "1234567890123456789012345678901234567890.12"}])
        with localcontext() as context:
            context.prec = 3
            self.check(value, [])
            value.total = Decimal("1234567890123456789012345678901234567890.13")
            self.check(value, [("total_mismatch", "total")])

    def test_negative_discount_direct_validation(self):
        self.check(data(discount="-6.40"), [("invalid_discount", "discount")])

    def test_unknown_item_amount_skips_sum_only(self):
        self.check(complete(total="83.30", items=[{"quantity": "2", "unit_price": "5.00", "amount": None}]),
                   [("total_mismatch", "total")])

    def test_unknown_formula_component_keeps_line_checks(self):
        self.check(complete(tax=None, items=[{"quantity": "2", "unit_price": "5.00", "amount": "9.00"}]),
                   [("item_amount_mismatch", "items[0].amount"), ("subtotal_mismatch", "subtotal")])


def missing_case(field, value):
    def test(self):
        self.check(data(**{field: value}), [("missing_" + field, field)])
    return test


for _field in ("merchant", "date", "currency", "total"):
    setattr(ValidationContract, f"test_null_required_{_field}", missing_case(_field, None))
for _field in ("merchant", "currency"):
    for _label, _value in (("empty", ""), ("whitespace", " \t\r\n")):
        setattr(ValidationContract, f"test_{_label}_{_field}", missing_case(_field, _value))


def precision_case(field, amount):
    def test(self):
        value = data(**{field: amount}) if "." not in field else data(items=[{
            field.split(".")[1]: amount}])
        self.check(value, [("invalid_amount_precision", field)])
    return test


for _field in ("total", "subtotal", "tax", "tip", "discount", "items[0].unit_price", "items[0].amount"):
    for _label, _amount in (("fractional_cent", "1.007"), ("tiny", "0.00000000000000000001")):
        setattr(ValidationContract, f"test_precision_{_field.replace('.', '_')}_{_label}",
                precision_case(_field, _amount))


def trailing_zero_case(field):
    def test(self):
        value = data(**{field: "17.230000"}) if "." not in field else data(items=[{
            field.split(".")[1]: "17.230000"}])
        self.check(value, [])
    return test


for _field in ("total", "subtotal", "tax", "tip", "discount", "items[0].unit_price", "items[0].amount"):
    setattr(ValidationContract, f"test_trailing_zeros_{_field.replace('.', '_')}", trailing_zero_case(_field))


def unknown_formula_case(field):
    def test(self):
        value = complete(total="999.99", **{field: None}) if field != "total" else complete(total=None)
        self.check(value, [("missing_total", "total")] if field == "total" else [])
    return test


for _field in ("subtotal", "discount", "tax", "tip", "total"):
    setattr(ValidationContract, f"test_unknown_formula_{_field}", unknown_formula_case(_field))


def partial_item_case(field):
    def test(self):
        item = {"quantity": "2", "unit_price": "5.00", "amount": "12.00"}
        item[field] = None
        self.check(data(items=[item]), [])
    return test


for _field in ("quantity", "unit_price", "amount"):
    setattr(ValidationContract, f"test_partial_line_{_field}", partial_item_case(_field))


def empty_items_case(items):
    def test(self):
        self.check(data(subtotal="99.00", items=items), [])
    return test


ValidationContract.test_null_items_skip_sum = empty_items_case(None)
ValidationContract.test_empty_items_skip_sum = empty_items_case([])


class NormalizationContract(unittest.TestCase):
    def test_only_discount_changes_even_with_conflicting_other_amounts(self):
        raw = complete(discount="-6.40", tax="-2.89", total="83.297", items=[
            {"description": "Original synthetic text", "quantity": "-3.125",
             "unit_price": "-4.005", "amount": "-12.01"}])
        snapshot = raw.model_dump_json()
        normalized, events = normalize_receipt_data(raw)
        expected = json.loads(snapshot)
        expected["discount"] = "6.40"
        self.assertEqual(normalized.model_dump(mode="json"), expected)
        self.assertEqual(raw.model_dump_json(), snapshot)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].original_value, Decimal("-6.40"))
        self.assertEqual(events[0].normalized_value, Decimal("6.40"))
        self.assertEqual(events[0].field, "discount")
        self.assertTrue(events[0].reason.strip())

    def test_parser_preserves_exact_raw_text_and_available_metadata(self):
        raw = " \n" + complete(discount="-6.40").model_dump_json(indent=2) + "\n "
        response = SimpleNamespace(status="completed", output_text=raw,
                                   id="synthetic-response-83", model="synthetic-offline-model",
                                   usage=SimpleNamespace(model_dump=lambda **kwargs: {"total_tokens": 37}))
        normalized, metadata = parse_extraction_with_metadata(response)
        self.assertEqual(metadata.raw_output, raw)
        self.assertEqual(metadata.response_id, "synthetic-response-83")
        self.assertEqual(metadata.model, "synthetic-offline-model")
        self.assertEqual(metadata.usage, {"total_tokens": 37})
        self.assertEqual(normalized.discount, Decimal("6.40"))
        self.assertEqual(metadata.normalizations[0].original_value, Decimal("-6.40"))


def normalization_case(discount):
    def test(self):
        raw = complete(discount=discount)
        before = raw.model_dump_json()
        result, events = normalize_receipt_data(raw)
        again, repeated_events = normalize_receipt_data(result)
        expected = None if discount is None else Decimal(discount).copy_abs()
        self.assertEqual(result.discount, expected)
        self.assertEqual(again.model_dump_json(), result.model_dump_json())
        self.assertEqual(raw.model_dump_json(), before)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].original_value, raw.discount)
        self.assertEqual(events[0].normalized_value, expected)
        self.assertTrue(events[0].reason.strip())
        self.assertEqual(len(repeated_events), 1)
        self.assertTrue(repeated_events[0].reason.strip())
    return test


for _label, _discount in (("negative", "-6.40"), ("positive", "6.40"),
                          ("zero", "0.00"), ("negative_zero", "-0.00"), ("null", None)):
    setattr(NormalizationContract, f"test_{_label}_audit_and_idempotence", normalization_case(_discount))
