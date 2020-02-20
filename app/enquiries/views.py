from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework import generics, viewsets, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.renderers import JSONRenderer, TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from app.enquiries import models, serializers


class PaginationHandlerMixin:
    """
    Mixin for handling pagination in APIView
    """

    @property
    def paginator(self):
        if not hasattr(self, "_paginator"):
            if self.pagination_class is None:
                self._paginator = None
            else:
                self._paginator = self.pagination_class()
        else:
            pass
        return self._paginator

    def paginate_queryset(self, queryset, request):
        if self.paginator is None:
            return None
        paginated_response = self.paginator.paginate_queryset(
            queryset, request, view=self
        )
        return paginated_response

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data)


class EnquiryListPagination(PageNumberPagination):
    page_size_query_param = "limit"
    page_size = settings.ENQUIRIES_PER_PAGE


class EnquiryListView(APIView, PaginationHandlerMixin):
    """
    List all enquiries.

    In GET: Returns a paginated list of enquiries
    """

    pagination_class = EnquiryListPagination
    renderer_classes = (JSONRenderer, TemplateHTMLRenderer)

    def get(self, request, format=None):
        enquiries = models.Enquiry.objects.all()
        paged_queryset = self.paginate_queryset(enquiries, request)
        if paged_queryset:
            paged_serializer = serializers.EnquiryDetailSerializer(
                paged_queryset, many=True
            )
            serializer = self.get_paginated_response(paged_serializer.data)
        else:
            serializer = serializers.EnquiryDetailSerializer(enquiries, many=True)

        return Response(
            {"serializer": serializer.data}, template_name="enquiry_list.html",
        )
