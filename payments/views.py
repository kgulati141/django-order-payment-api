import hashlib
import hmac
import json

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Payment, WebhookEvent
from django.db import IntegrityError, transaction

from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema, OpenApiParameter

from orders.models import Order
from .models import Payment
from .serializers import (
    PaymentCreateSerializer,
    PaymentReadSerializer,
)

from .tasks import send_payment_notification

class PaymentListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Payment.objects
            .filter(order__user=self.request.user)
            .select_related("order")
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PaymentCreateSerializer
        return PaymentReadSerializer

    def existing_payment_response(
        self, payment, order, method, request
    ):
        if payment is None:
            return None

        same_request = (
            payment.order_id == order.id
            and payment.order.user_id == request.user.id
            and payment.payment_method == method
        )

        if same_request:
            return Response(
                PaymentReadSerializer(payment).data,
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "detail": (
                    "This Idempotency-Key has already been "
                    "used for a different request."
                )
            },
            status=status.HTTP_409_CONFLICT,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description=(
                    "Unique key for this payment attempt. "
                    "Reuse the same key when retrying."
                ),
            )
        ],
        request=PaymentCreateSerializer,
        responses={
            200: PaymentReadSerializer,
            201: PaymentReadSerializer,
        },
    )
    def create(self, request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key", "").strip()

        if not key:
            raise serializers.ValidationError({
                "Idempotency-Key": "This header is required."
            })

        if len(key) > 255:
            raise serializers.ValidationError({
                "Idempotency-Key": "Maximum length is 255 characters."
            })

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = serializer.validated_data["order"]
        method = serializer.validated_data["payment_method"]

        existing = (
            Payment.objects
            .filter(idempotency_key=key)
            .select_related("order")
            .first()
        )

        replay = self.existing_payment_response(
            existing, order, method, request
        )
        if replay is not None:
            return replay

        try:
            with transaction.atomic():
                locked_order = (
                    Order.objects
                    .select_for_update()
                    .filter(pk=order.pk, user=request.user)
                    .first()
                )

                if locked_order is None:
                    return Response(
                        {"detail": "Order not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Recheck the key after acquiring the order lock.
                existing = (
                    Payment.objects
                    .filter(idempotency_key=key)
                    .select_related("order")
                    .first()
                )

                replay = self.existing_payment_response(
                    existing, locked_order, method, request
                )
                if replay is not None:
                    return replay

                if locked_order.status != "PENDING":
                    return Response(
                        {"detail": "Only pending orders can be paid."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if locked_order.total_amount <= 0:
                    return Response(
                        {"detail": "Order amount must be greater than zero."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                active_payment = Payment.objects.filter(
                    order=locked_order,
                    status__in=["PENDING", "SUCCEEDED"],
                ).first()

                if active_payment:
                    return Response(
                        {
                            "detail": (
                                "An active payment already exists "
                                "for this order. Reuse its "
                                "Idempotency-Key for retries."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                payment = Payment.objects.create(
                    order=locked_order,
                    amount=locked_order.total_amount,
                    currency="INR",
                    payment_method=method,
                    status="PENDING",
                    idempotency_key=key,
                )

        except IntegrityError:
            # A concurrent request may have used this unique key.
            existing = (
                Payment.objects
                .filter(idempotency_key=key)
                .select_related("order")
                .first()
            )

            if existing is None:
                raise

            replay = self.existing_payment_response(
                existing, order, method, request
            )
            if replay is not None:
                return replay

            return Response(
                {"detail": "Idempotency-Key conflict."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            PaymentReadSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )


class PaymentWebhookView(APIView):
    # The provider authenticates using HMAC, not a user JWT.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        raw_body = request.body
        received_signature = request.headers.get(
            "X-Webhook-Signature", ""
        )

        expected_signature = "sha256=" + hmac.new(
            settings.WEBHOOK_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            received_signature, expected_signature
        ):
            return Response(
                {"detail": "Invalid webhook signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Response(
                {"detail": "Invalid JSON payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(payload, dict):
            return Response(
                {"detail": "JSON body must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_id = payload.get("id")
        event_type = payload.get("type")
        data = payload.get("data")

        if (
            not isinstance(event_id, str)
            or not event_id.strip()
            or len(event_id.strip()) > 255
            or event_type not in {
                "payment.succeeded",
                "payment.failed",
            }
            or not isinstance(data, dict)
        ):
            return Response(
                {"detail": "Invalid webhook event."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_id = event_id.strip()
        payment_id = data.get("payment_id")

        if (
            isinstance(payment_id, bool)
            or not isinstance(payment_id, int)
            or payment_id <= 0
        ):
            return Response(
                {"detail": "Invalid payment_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                existing = WebhookEvent.objects.filter(
                    event_id=event_id
                ).first()

                if existing:
                    return Response(
                        {
                            "detail": "Duplicate event ignored.",
                            "event_id": event_id,
                        },
                        status=status.HTTP_200_OK,
                    )

                payment = (
                    Payment.objects
                    .select_for_update()
                    .select_related("order")
                    .filter(pk=payment_id)
                    .first()
                )

                if payment is None:
                    return Response(
                        {"detail": "Payment not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Recheck after locking the payment.
                existing = WebhookEvent.objects.filter(
                    event_id=event_id
                ).first()

                if existing:
                    return Response(
                        {
                            "detail": "Duplicate event ignored.",
                            "event_id": event_id,
                        },
                        status=status.HTTP_200_OK,
                    )

                event = WebhookEvent.objects.create(
                    event_id=event_id,
                    event_type=event_type,
                    payload=payload,
                    processing_status="RECEIVED",
                )

                if event_type == "payment.succeeded":
                    if payment.status in {"FAILED", "REFUNDED"}:
                        event.processing_status = "ERROR"
                        event.error_message = (
                            f"Cannot mark a {payment.status} "
                            "payment as succeeded."
                        )
                        event.processed_at = timezone.now()
                        event.save(
                            update_fields=[
                                "processing_status",
                                "error_message",
                                "processed_at",
                            ]
                        )
                        return Response(
                            {
                                "detail": event.error_message
                            },
                            status=status.HTTP_409_CONFLICT,
                        )

                    if payment.status != "SUCCEEDED":
                        payment.status = "SUCCEEDED"
                        payment.save(update_fields=["status", "updated_at"])

                        transaction.on_commit(
                            lambda payment_id=payment.id:
                                send_payment_notification.delay(payment_id)
                        )

                    if payment.order.status == "PENDING":
                        payment.order.status = "CONFIRMED"
                        payment.order.save(
                            update_fields=["status", "updated_at"]
                        )

                else:  # payment.failed
                    # Never downgrade a successful payment.
                    if payment.status == "PENDING":
                        payment.status = "FAILED"
                        payment.save(
                            update_fields=["status", "updated_at"]
                        )

                event.processing_status = "PROCESSED"
                event.processed_at = timezone.now()
                event.save(
                    update_fields=[
                        "processing_status",
                        "processed_at",
                    ]
                )

        except IntegrityError:
            # Handles a concurrent duplicate event insert.
            existing = WebhookEvent.objects.filter(
                event_id=event_id
            ).first()

            if existing:
                return Response(
                    {
                        "detail": "Duplicate event ignored.",
                        "event_id": event_id,
                    },
                    status=status.HTTP_200_OK,
                )

            raise

        return Response(
            {
                "detail": "Webhook processed.",
                "event_id": event_id,
            },
            status=status.HTTP_200_OK,
        )
