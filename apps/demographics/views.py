from rest_framework import viewsets
from django.db.models import Q
from common.permissions import RolePermission
from common.facility_scope import filter_by_facility
from .models import Patient
from .serializers import PatientSerializer, PatientIdentitySerializer

class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all().order_by('-id')
    serializer_class = PatientSerializer
    permission_classes = [RolePermission]
    role_map = {
        'GET': ['admin', 'reception', 'clinician', 'nurse', 'pharmacy', 'lab', 'cashier', 'manager'],
        'POST': ['admin','reception'],
        'PUT': ['admin','reception'],
        'PATCH': ['admin','reception'],
        'DELETE': ['admin'],
    }
    def get_serializer_class(self):
        # Worklist/search roles need identity, not the full registration record.
        if getattr(self, 'swagger_fake_view', False):
            return PatientSerializer
        user = self.request.user
        if self.request.method in ('GET', 'HEAD', 'OPTIONS') and not (
            user.is_superuser or getattr(user, 'role', None) in ('admin', 'reception', 'clinician')
        ):
            return PatientIdentitySerializer
        return PatientSerializer

    def get_queryset(self):
        qs = filter_by_facility(super().get_queryset(), self.request.user)
        q = self.request.query_params.get('q')
        if q:
            q = q.strip()
            id_match = None
            try:
                id_match = int(q)
            except Exception:
                id_match = None
            filters = (
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(other_names__icontains=q) |
                Q(phone__icontains=q)
            )
            if id_match is not None:
                filters = filters | Q(id=id_match)
            qs = qs.filter(filters)
        return qs
