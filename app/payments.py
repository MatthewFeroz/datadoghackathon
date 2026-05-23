from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_payment(x_dev_payment: str | None = Header(default=None)) -> None:
    settings = get_settings()

    if settings.dev_payment_bypass and x_dev_payment == "paid":
        return

    # Replace this with x402/MPP verification for the live demo.
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail="Payment required. In development, pass X-Dev-Payment: paid.",
    )
