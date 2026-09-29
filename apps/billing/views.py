from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.response import Response
from django.db import transaction

from .models import PriceListItem, Invoice, Payment, CashSession
from .serializers import PriceListItemSerializer, InvoiceSerializer, PaymentSerializer
from .services import recalc_invoice
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

class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all().order_by('-paid_at')
    serializer_class = PaymentSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','cashier'],
        'PUT': ['admin','cashier'],
        'PATCH': ['admin','cashier'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(
            super().get_queryset(),
            self.request.user,
            prefix='invoice__patient__',
        )

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        invoice_id = data.get('invoice')
        try:
            amount = Decimal(data.get('amount', '0'))
        except Exception:
            return Response({'detail': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)
        user = request.user
        invoice = (
            filter_by_patient_facility(Invoice.objects.all(), user)
            .select_related('patient')
            .filter(pk=invoice_id)
            .first()
        )
        if not invoice:
            return Response({'detail': 'Invoice not found'}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure an open cash session per cashier
        session = CashSession.objects.filter(opened_by=user, close_time__isnull=True).first()
        if session is None:
            session = CashSession.objects.create(opened_by=user)

        with transaction.atomic():
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            payment = Payment.objects.get(pk=serializer.data['id'])
            # Attach session if not set (serializer may not include cash_session field)
            if payment.cash_session_id is None:
                payment.cash_session = session
                payment.save(update_fields=['cash_session'])

            # Update invoice and session expected cash
            invoice.paid_amount = (invoice.paid_amount or Decimal('0')) + amount
            if invoice.paid_amount >= invoice.total_amount:
                invoice.status = Invoice.PAID
            invoice.save(update_fields=['paid_amount', 'status'])
            recalc_invoice(invoice)

            session.expected_cash = (session.expected_cash or Decimal('0')) + amount
            session.save(update_fields=['expected_cash'])

            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
