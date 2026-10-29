
import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_orders_api_requires_authentication():
    client = APIClient()

    response = client.get("/api/orders/")

    assert response.status_code == 401
