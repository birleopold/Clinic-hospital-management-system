from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError
from django.db.models import Sum
from common.permissions import RolePermission
from common.facility_scope import filter_by_patient_facility
from .models import Dispense, Prescription, PrescriptionItem
from .serializers import DispenseSerializer, PrescriptionSerializer, PrescriptionItemSerializer
from apps.inventory.models import InventoryItem, Batch


class PrescriptionViewSet(viewsets.ModelViewSet):
    queryset = Prescription.objects.all().order_by('-id')
    serializer_class = PrescriptionSerializer
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','clinician','pharmacy','nurse'],
        'POST': ['admin','clinician'],
        'PUT': ['admin','clinician'],
        'PATCH': ['admin','clinician'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(super().get_queryset(), self.request.user)


class PrescriptionItemViewSet(viewsets.ModelViewSet):
    queryset = PrescriptionItem.objects.all().order_by('-id')
    serializer_class = PrescriptionItemSerializer
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','clinician','pharmacy','nurse'],
        'POST': ['admin','clinician'],
        'PUT': ['admin','clinician'],
        'PATCH': ['admin','clinician'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(
            super().get_queryset(),
            self.request.user,
            prefix='prescription__patient__',
        )


class DispenseViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                      mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Dispense.objects.all().order_by('-id')
    serializer_class = DispenseSerializer
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin','clinician','pharmacy','nurse'],
        'POST': ['admin','pharmacy'],
        'PUT': ['admin','pharmacy'],
        'PATCH': ['admin','pharmacy'],
        'DELETE': ['admin'],
    }

    def get_queryset(self):
        return filter_by_patient_facility(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        item_code = serializer.validated_data.get('item_code')
        qty = serializer.validated_data.get('quantity') or 0
        sel_batch = serializer.validated_data.get('batch')
        if not item_code:
            raise ValidationError({'item_code': 'This field is required.'})
        try:
            item = InventoryItem.objects.get(code=item_code)
        except InventoryItem.DoesNotExist:
            raise ValidationError({'item_code': 'Unknown inventory item code.'})
        from common.facility_scope import filter_by_facility
        from .services import usable_batches
        batches = filter_by_facility(usable_batches().filter(item=item), self.request.user, field='location__facility_id')
        patient = serializer.validated_data['patient']
        if patient.facility_id:
            batches = batches.filter(location__facility_id=patient.facility_id)
        available = batches.aggregate(total=Sum('quantity_on_hand'))['total'] or 0
        if qty > available:
            raise ValidationError({'quantity': f'Insufficient stock. Available: {available}.'})
        # Determine batch: prefer provided batch; else FEFO with enough quantity
        selected_batch = None
        if sel_batch is not None:
            if sel_batch.item_id != item.id:
                raise ValidationError({'batch': 'Selected batch does not match item.'})
            if not batches.filter(pk=sel_batch.pk).exists():
                raise ValidationError({'batch': 'Choose usable, unexpired stock in the patient facility.'})
            if (sel_batch.quantity_on_hand or 0) < qty:
                raise ValidationError({'batch': f'Selected batch has only {sel_batch.quantity_on_hand} available.'})
            selected_batch = sel_batch
        else:
            selected_batch = (
                batches.filter(quantity_on_hand__gte=qty)
                .first()
            )
            if not selected_batch:
                raise ValidationError({'batch': 'Insufficient in a single batch. Specify a batch or lower the quantity.'})

        from django.core.exceptions import ValidationError as ModelValidationError
        try:
            serializer.save(batch=selected_batch)
        except ModelValidationError as exc:
            raise ValidationError({'detail': exc.messages})
