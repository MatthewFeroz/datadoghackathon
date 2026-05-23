from typing import Literal

from fastapi import Header, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings


class PaymentReceipt(BaseModel):
    payment_id: str
    amount_cents: int
    currency: str


def price_for_severity(severity: Literal["low", "medium", "high"]) -> int:
    settings = get_settings()
    prices = {
        "low": settings.stripe_low_severity_cents,
        "medium": settings.stripe_medium_severity_cents,
        "high": settings.stripe_high_severity_cents,
    }
    return min(prices[severity], 50)


def format_dollars(amount_cents: int | None) -> str:
    amount_cents = amount_cents or 0
    return f"${amount_cents / 100:.2f}"


def _stripe_client():
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured. Set STRIPE_SECRET_KEY.",
        )
    try:
        import stripe
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe package is not installed. Run pip install -r requirements.txt in your virtualenv.",
        ) from exc
    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_checkout_session(
    *,
    run_id: str,
    gap_index: int,
    title: str,
    severity: Literal["low", "medium", "high"],
) -> str:
    stripe = _stripe_client()
    settings = get_settings()
    amount_cents = price_for_severity(severity)
    success_url = (
        f"{settings.app_base_url}/payments/success"
        f"?session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{settings.app_base_url}/"

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": settings.stripe_currency,
                    "product_data": {
                        "name": f"Agent-authored docs fix: {title}",
                        "description": (
                            f"Agent workflow for a {severity} documentation gap. "
                            "The agent publishes the fix after payment."
                        ),
                    },
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }
        ],
        metadata={
            "run_id": run_id,
            "gap_index": str(gap_index),
            "severity": severity,
        },
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return str(session.url)


def verify_checkout_session(session_id: str) -> tuple[PaymentReceipt, str, int]:
    stripe = _stripe_client()
    session = stripe.checkout.Session.retrieve(session_id)
    if session.payment_status != "paid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Stripe checkout session is not paid.",
        )

    metadata = session.metadata or {}
    run_id = metadata.get("run_id")
    gap_index = metadata.get("gap_index")
    if not run_id or gap_index is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stripe checkout session is missing run metadata.",
        )

    receipt = PaymentReceipt(
        payment_id=str(session.payment_intent or session.id),
        amount_cents=int(session.amount_total or 0),
        currency=str(session.currency or get_settings().stripe_currency),
    )
    return receipt, str(run_id), int(gap_index)


async def require_payment(x_dev_payment: str | None = Header(default=None)) -> None:
    settings = get_settings()

    if settings.dev_payment_bypass and x_dev_payment == "paid":
        return

    # Replace this with x402/MPP verification for the live demo.
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail="Payment required. In development, pass X-Dev-Payment: paid.",
    )
