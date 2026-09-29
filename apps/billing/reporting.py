from decimal import Decimal
from django.db.models import Sum
from common.facility_scope import filter_by_patient_facility
from apps.operations.models import Refund

def refunded_between(user, start, end):
    return filter_by_patient_facility(Refund.objects.filter(status='approved',approved_at__range=(start,end)),user,prefix='payment__invoice__patient__').aggregate(total=Sum('amount'))['total'] or Decimal('0')
