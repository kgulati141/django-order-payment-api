
from celery import shared_task


@shared_task
def add_numbers(a, b):
    return a + b


import smtplib

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from .models import Payment


@shared_task(
    bind=True,
    autoretry_for=(OSError, smtplib.SMTPException),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def send_payment_notification(self, payment_id):
    try:
        payment = Payment.objects.select_related(
            "order__user"
        ).get(pk=payment_id)
    except Payment.DoesNotExist:
        return {"status": "skipped", "reason": "payment_not_found"}

    if payment.status != "SUCCEEDED":
        return {
            "status": "skipped",
            "reason": "payment_not_succeeded",
        }

    recipient = payment.order.user.email

    if not recipient:
        return {"status": "skipped", "reason": "user_email_missing"}

    sent = send_mail(
        subject=f"Payment successful - #{payment.id}",
        message=(
            f"Your payment of {payment.currency} "
            f"{payment.amount} for order #{payment.order_id} "
            "was successful."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )

    if sent != 1:
        raise OSError("Payment notification could not be sent.")

    return {"status": "sent", "payment_id": payment.id}
