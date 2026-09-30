from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Min, Q
from django.shortcuts import render
from django.utils import timezone
from apps.appointments.models import QueueTicket
from apps.orders.models import Order
from common.facility_scope import filter_by_facility
from .extension_services import role
from .models import Claim, WorkTask


@login_required
def insights(request):
    role(request.user, ('admin','manager'))
    try: days=max(1,min(90,int(request.GET.get('days',30))))
    except (TypeError,ValueError): days=30
    now=timezone.now(); start=now-timedelta(days=days)
    queue=filter_by_facility(QueueTicket.objects.filter(created_at__gte=start,created_at__lte=now),request.user,'patient__facility_id')
    orders=filter_by_facility(Order.objects.filter(created_at__gte=start,created_at__lte=now,order_type__in=['lab','imaging']),request.user,'patient__facility_id').annotate(first_release=Min('results__approved_at'))
    claims=filter_by_facility(Claim.objects.filter(created_at__gte=start,created_at__lte=now),request.user,'invoice__patient__facility_id')
    waits=[]
    for service,label in QueueTicket.SERVICE_CHOICES:
        subset=queue.filter(service=service)
        valid=subset.filter(started_at__gte=F('created_at')).exclude(status='cancelled')
        total=subset.count(); eligible=valid.count()
        duration=valid.aggregate(value=Avg(F('started_at')-F('created_at')))['value']
        waits.append((label,total,eligible,total-eligible,round(duration.total_seconds()/60,1) if duration is not None else None))
    turnaround=[]
    for kind in ('lab','imaging'):
        subset=orders.filter(order_type=kind)
        valid=subset.filter(first_release__gte=F('created_at')).exclude(status='cancelled')
        total=subset.count(); eligible=valid.count()
        duration=valid.aggregate(value=Avg(F('first_release')-F('created_at')))['value']
        turnaround.append((kind,total,eligible,total-eligible,round(duration.total_seconds()/3600,2) if duration is not None else None))
    payers=[]
    for item in claims.values('payer__name').annotate(total=Count('pk'),accepted=Count('pk',filter=Q(status='accepted')),rejected=Count('pk',filter=Q(status='rejected'))).order_by('payer__name'):
        denominator=item['accepted']+item['rejected']
        item['denominator']=denominator
        item['rate']=round(100*item['rejected']/denominator,1) if denominator else None
        payers.append(item)
    kind=request.GET.get('kind','queue')
    sources={'queue':queue.select_related('patient'),'orders':orders.select_related('patient'),'claims':claims.select_related('payer')}
    if kind not in sources:kind='queue'
    page=Paginator(sources[kind].order_by('-created_at','-pk'),30).get_page(request.GET.get('page'))
    overdue=filter_by_facility(WorkTask.objects.filter(due_at__lt=now).exclude(status__in=['completed','cancelled']),request.user).count()
    return render(request,'operations/insights.html',{'days':days,'start':start,'now':now,'waits':waits,'turnaround':turnaround,'payers':payers,'page':page,'kind':kind,'overdue':overdue})
