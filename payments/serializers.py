
from rest_framework import serializers

from orders.models import Order
from .models import Payment


class PaymentCreateSerializer(serializers.Serializer):
    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.none()
    )
    payment_method = serializers.ChoiceField(
        choices=Payment.METHOD_CHOICES
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["order"].queryset = Order.objects.filter(
                user=request.user
            )


class PaymentReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "order",
            "amount",
            "currency",
            "payment_method",
            "status",
            "provider_reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
