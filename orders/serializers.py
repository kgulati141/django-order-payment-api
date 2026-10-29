
from django.db import transaction
from rest_framework import serializers

from catalog.models import Product
from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="product.name",
        read_only=True,
    )
    subtotal = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = OrderItem
        fields = [
            "id", "product", "product_name",
            "quantity", "unit_price", "subtotal",
        ]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    username = serializers.CharField(
        source="user.username",
        read_only=True,
    )

    class Meta:
        model = Order
        fields = [
            "id", "username", "status",
            "total_amount", "items", "created_at",
        ]
        read_only_fields = fields


class OrderItemInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True)
    )
    quantity = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(serializers.Serializer):
    items = OrderItemInputSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_items(self, items):
        product_ids = [item["product"].id for item in items]

        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Each product must appear only once."
            )

        return items

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        requested_items = validated_data["items"]

        product_ids = [
            item["product"].id for item in requested_items
        ]

        products = {
            product.id: product
            for product in Product.objects
            .select_for_update()
            .filter(id__in=product_ids, is_active=True)
            .order_by("id")
        }

        if len(products) != len(product_ids):
            raise serializers.ValidationError(
                "One or more products are unavailable."
            )

        total = 0
        order_lines = []

        for item in requested_items:
            product = products[item["product"].id]
            quantity = item["quantity"]

            if product.stock < quantity:
                raise serializers.ValidationError(
                    f"Insufficient stock for {product.name}."
                )

            price = product.price
            total += price * quantity
            order_lines.append((product, quantity, price))

        order = Order.objects.create(
            user=user,
            total_amount=total,
            status="PENDING",
        )

        for product, quantity, price in order_lines:
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                unit_price=price,
            )

            product.stock -= quantity
            product.save(update_fields=["stock"])

        return order
