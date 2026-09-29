from datetime import datetime
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseForbidden
from django.utils import timezone
from django.db.models import Sum

from apps.billing.models import Payment
from common.facility_scope import filter_by_patient_facility


@login_required
def reports_dashboard_view(request):
    user = request.user
    if not (user.is_superuser or user.role in ('admin','manager','cashier')):
        return HttpResponseForbidden('Not allowed')
    today = timezone.localdate()
    start = timezone.make_aware(datetime(today.year, today.month, today.day, 0, 0, 0))
    end = timezone.make_aware(datetime(today.year, today.month, today.day, 23, 59, 59))
    pay = filter_by_patient_facility(Payment.objects.all(), user, prefix='invoice__patient__')
    revenue_today = pay.filter(paid_at__range=(start, end)).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    # Month-to-date
    mstart = timezone.make_aware(datetime(today.year, today.month, 1, 0, 0, 0))
    mend = end
    revenue_mtd = pay.filter(paid_at__range=(mstart, mend)).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    from apps.billing.reporting import refunded_between
    revenue_today -= refunded_between(request.user,start,end)
    revenue_mtd -= refunded_between(request.user,mstart,mend)
    context = {
        'revenue_today': revenue_today,
        'revenue_mtd': revenue_mtd,
    }
    return render(request, 'reports/dashboard.html', context)
