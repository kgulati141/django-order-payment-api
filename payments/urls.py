from django.urls import path
from .views import PaymentListCreateView, PaymentWebhookView

urlpatterns = [
    path(
        "payments/",
        PaymentListCreateView.as_view(),
        name="payment-list-create",
    ),
    path(
        "webhooks/payment/",
        PaymentWebhookView.as_view(),
        name="payment-webhook",
    ),
]