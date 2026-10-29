
import pytest
from rest_framework.test import APIClient

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from orders.models import Order
from payments.models import Payment, WebhookEvent


@pytest.mark.django_db
def test_payments_api_requires_authentication():
    client = APIClient()

    response = client.get("/api/payments/")

    assert response.status_code == 401


WEBHOOK_URL = "/api/webhooks/payment/"


def create_test_payment():
    user = get_user_model().objects.create_user(
        username="webhook-test-user",
        password="test-password-123",
    )

    order = Order.objects.create(
        user=user,
        status="PENDING",
        total_amount=Decimal("150.00"),
    )

    payment = Payment.objects.create(
        order=order,
        amount=Decimal("150.00"),
        currency="INR",
        payment_method="UPI",
        status="PENDING",
        idempotency_key="webhook-test-payment-key",
    )

    return order, payment


def send_signed_webhook(
    client,
    secret,
    payment_id,
    event_id,
    event_type="payment.succeeded",
    signature_override=None,
):
    payload = {
        "id": event_id,
        "type": event_type,
        "data": {"payment_id": payment_id},
    }

    raw_body = json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")

    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if signature_override is not None:
        signature = signature_override

    return client.generic(
        "POST",
        WEBHOOK_URL,
        data=raw_body,
        content_type="application/json",
        HTTP_X_WEBHOOK_SIGNATURE=signature,
    )


@pytest.mark.django_db
def test_webhook_rejects_invalid_signature(settings):
    settings.WEBHOOK_SECRET = "test-webhook-secret"
    _, payment = create_test_payment()

    response = send_signed_webhook(
        APIClient(),
        settings.WEBHOOK_SECRET,
        payment.id,
        "evt-invalid-signature",
        signature_override="sha256=invalid",
    )

    assert response.status_code == 401

    payment.refresh_from_db()
    assert payment.status == "PENDING"
    assert not WebhookEvent.objects.filter(
        event_id="evt-invalid-signature"
    ).exists()


@pytest.mark.django_db
def test_valid_success_webhook_confirms_order(settings):
    settings.WEBHOOK_SECRET = "test-webhook-secret"
    order, payment = create_test_payment()

    response = send_signed_webhook(
        APIClient(),
        settings.WEBHOOK_SECRET,
        payment.id,
        "evt-valid-success",
    )

    assert response.status_code == 200

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == "SUCCEEDED"
    assert order.status == "CONFIRMED"

    event = WebhookEvent.objects.get(
        event_id="evt-valid-success"
    )
    assert event.processing_status == "PROCESSED"


@pytest.mark.django_db
def test_duplicate_webhook_is_not_processed_twice(settings):
    settings.WEBHOOK_SECRET = "test-webhook-secret"
    _, payment = create_test_payment()
    client = APIClient()

    first = send_signed_webhook(
        client,
        settings.WEBHOOK_SECRET,
        payment.id,
        "evt-duplicate-test",
    )

    second = send_signed_webhook(
        client,
        settings.WEBHOOK_SECRET,
        payment.id,
        "evt-duplicate-test",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.data["detail"] == "Duplicate event ignored."

    assert WebhookEvent.objects.filter(
        event_id="evt-duplicate-test"
    ).count() == 1
