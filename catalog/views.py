
import hashlib

from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import Product
from .serializers import ProductSerializer


def invalidate_product_cache():
    # django-redis supports deleting keys by pattern.
    cache.delete_pattern("products:list:*")


class ProductViewSet(ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    filterset_fields = ["is_active"]
    search_fields = ["name", "description"]
    ordering_fields = ["price", "created_at"]

    def list(self, request, *args, **kwargs):
        # Include query parameters so searches and pages cache separately.
        path = request.get_full_path()
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        cache_key = f"products:list:{digest}"

        cached_data = cache.get(cache_key)

        if cached_data is not None:
            return Response(
                cached_data,
                headers={"X-Cache": "HIT"},
            )

        response = super().list(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            cache.set(cache_key, response.data, timeout=300)

        response["X-Cache"] = "MISS"
        return response

    def perform_create(self, serializer):
        serializer.save()
        invalidate_product_cache()

    def perform_update(self, serializer):
        serializer.save()
        invalidate_product_cache()

    def perform_destroy(self, instance):
        instance.delete()
        invalidate_product_cache()
