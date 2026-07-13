import hashlib
import hmac
import json

from fastapi import APIRouter, Request

from app.otp.service import OTPError

router = APIRouter(prefix="/webhooks/otp", tags=["webhooks"])


@router.post("/termii")
async def termii_delivery_report(request: Request) -> dict[str, bool]:
    body = await request.body()
    signature = request.headers.get("x-termii-signature", "")
    secret = request.app.state.settings.termii_webhook_secret
    expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    if not secret or not hmac.compare_digest(signature, expected):
        raise OTPError("invalid_webhook_signature")
    try:
        payload = json.loads(body)
        message_id = str(payload["message_id"])
        status = str(payload["status"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise OTPError("invalid_webhook_payload") from exc
    request.app.state.otp_service.confirm_delivery("termii", message_id, status)
    return {"received": True}
