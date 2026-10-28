from app.contracts import FeatureNotImplementedError
from app.schemas.receipt import NotificationResult, ReceiptResponse


def record_notification(receipt: ReceiptResponse) -> NotificationResult:
    raise FeatureNotImplementedError("Notification recording is not implemented")
