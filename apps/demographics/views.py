from rest_framework import viewsets
from django.db.models import Q
from common.permissions import RolePermission
from common.facility_scope import filter_by_facility
from .models import Patient
from .serializers import PatientSerializer

class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all().order_by('-id')
    serializer_class = PatientSerializer
    permission_classes = [RolePermission]
    role_map = {
        'POST': ['admin','reception'],
        'PUT': ['admin','reception'],
        'PATCH': ['admin','reception'],
        'DELETE': ['admin'],
    }
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
