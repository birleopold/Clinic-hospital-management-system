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

    def create(self, request, *args, **kwargs):
        from django.core.exceptions import ValidationError as ModelValidationError
        from django.db import IntegrityError
        from .payment_services import collect_cash
        serializer=self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        if data.get('method','cash')!='cash':
            raise ValidationError({'method':'Use verified collection or remittance workflows for non-cash payments.'})
        try:
            payment,created=collect_cash(data['invoice'].pk,request.user,data['amount'],data['idempotency_key'],data.get('notes',''))
        except ModelValidationError as exc:
            raise ValidationError({'detail':exc.messages})
        except IntegrityError as exc:
            if 'Patient identity was merged' in str(exc):raise
            raise ValidationError({'idempotency_key':'Payment reference conflict. Reload and check the payment ledger before retrying.'})
        return Response(self.get_serializer(payment).data,status=201 if created else 200)
