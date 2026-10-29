
from django.db import models
from orders.models import Order


class Payment(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
        ("REFUNDED", "Refunded"),
    ]

    METHOD_CHOICES = [
        ("CARD", "Card"),
        ("UPI", "UPI"),
        ("NETBANKING", "Net Banking"),
        ("WALLET", "Wallet"),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default="INR",
    )

    payment_method = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
        db_index=True,
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )

    provider_reference = models.CharField(
        max_length=100,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "status"]),
        ]

    def __str__(self):
        return f"Payment #{self.id} - {self.status}"


class WebhookEvent(models.Model):
    PROCESSING_STATUS_CHOICES = [
        ("RECEIVED", "Received"),
        ("PROCESSED", "Processed"),
        ("ERROR", "Error"),
    ]

    # Unique ID supplied by the webhook sender.
    event_id = models.CharField(
        max_length=255,
        unique=True,
    )

    event_type = models.CharField(max_length=100)

    # Save the incoming JSON payload for auditing and debugging.
    payload = models.JSONField()

    processing_status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS_CHOICES,
        default="RECEIVED",
        db_index=True,
    )

    error_message = models.CharField(
        max_length=500,
        blank=True,
    )

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_id} - {self.processing_status}"
