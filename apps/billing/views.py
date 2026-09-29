from apps.operations.models import Refund
from decimal import Decimal
from rest_framework import mixins, viewsets, status
from rest_framework.response import Response
from django.db import transaction
from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from .models import PriceListItem, Invoice, Payment, CashSession
from .serializers import PriceListItemSerializer, InvoiceSerializer, PaymentSerializer
from common.permissions import RolePermission
from common.facility_scope import filter_by_patient_facility

class PriceListItemViewSet(viewsets.ModelViewSet):
    queryset = PriceListItem.objects.all().order_by('code')
    serializer_class = PriceListItemSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin'],
        'PUT': ['admin'],
        'PATCH': ['admin'],
        'DELETE': ['admin'],
    }

class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Invoice.objects.all().order_by('-id')
    serializer_class = InvoiceSerializer
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','manager','cashier']
    }

    def get_queryset(self):
        return filter_by_patient_facility(super().get_queryset(), self.request.user)

class PaymentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                     mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Payment.objects.all().order_by('-paid_at')
    serializer_class = PaymentSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','cashier'],
        'GET': ['admin','manager','cashier'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(
            super().get_queryset(),
            self.request.user,
            prefix='invoice__patient__',
        )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Serialize payments by cashier, then invoice, to avoid lost totals and
        # duplicate automatically opened sessions on PostgreSQL.
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        invoice = Invoice.objects.select_for_update().get(
            pk=serializer.validated_data['invoice'].pk
        )
        amount = serializer.validated_data['amount']
        if invoice.status == Invoice.CANCELLED:
            raise ValidationError({'invoice': 'Cannot pay a cancelled invoice.'})
        paid = invoice.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        paid -= Refund.objects.filter(payment__invoice=invoice, status='approved').aggregate(total=Sum('amount'))['total'] or Decimal('0')
        if amount > invoice.total_amount - paid:
            raise ValidationError({'amount': 'Amount exceeds the outstanding balance.'})
        session = CashSession.objects.select_for_update().filter(
            opened_by=request.user, close_time__isnull=True
        ).first()
        if session is None:
            session = CashSession.objects.create(opened_by=request.user)
        serializer.save(invoice=invoice, cash_session=session)
        invoice.paid_amount = paid + amount
        if invoice.paid_amount >= invoice.total_amount:
            invoice.status = Invoice.PAID
        invoice.save(update_fields=['paid_amount', 'status'])
        session.expected_cash = session.opening_float + (
            session.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )
        session.expected_cash -= Refund.objects.filter(cash_session=session, status='approved').aggregate(total=Sum('amount'))['total'] or Decimal('0')
        session.save(update_fields=['expected_cash'])
        return Response(serializer.data, status=status.HTTP_201_CREATED,
                        headers=self.get_success_headers(serializer.data))
