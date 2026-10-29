
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from catalog.models import Product


@pytest.mark.django_db
def test_product_can_be_created_via_api(monkeypatch):
    # Keep this test independent of a running Redis cache.
    monkeypatch.setattr(
        "catalog.views.invalidate_product_cache",
        lambda: None,
    )

    client = APIClient()

    response = client.post(
        "/api/products/",
        {
            "name": "Test Mouse",
            "description": "Pytest sample product",
            "price": "799.00",
            "stock": 10,
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 201

    product = Product.objects.get(pk=response.data["id"])
    assert product.name == "Test Mouse"
    assert product.price == Decimal("799.00")
    assert product.stock == 10


@pytest.mark.django_db
def test_product_name_is_required():
    client = APIClient()

    response = client.post(
        "/api/products/",
        {
            "price": "799.00",
            "stock": 10,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "name" in response.data
