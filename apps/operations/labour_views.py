from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from common.facility_scope import filter_by_patient_facility
from .extension_services import role
from .models import Pregnancy


@login_required
def trend(request,pk):
    role(request.user,('admin','clinician','nurse'))
    pregnancy=get_object_or_404(filter_by_patient_facility(Pregnancy.objects.select_related('patient'),request.user),pk=pk)
    queryset=pregnancy.labour_observations.filter(amendment__isnull=True).select_related('created_by').order_by('-observed_at','-pk')
    total=queryset.count();rows=list(reversed(list(queryset[:200])))
    panels=[]
    if rows:
        start,end=rows[0].observed_at,rows[-1].observed_at
        seconds=max((end-start).total_seconds(),1)
        for field,label,unit in [('cervical_dilation_cm','Cervical dilation','cm'),('fetal_heart_rate','Fetal heart rate','beats/min'),('maternal_pulse','Maternal pulse','beats/min'),('systolic','Systolic blood pressure','mmHg'),('diastolic','Diastolic blood pressure','mmHg'),('temperature_c','Temperature','°C')]:
            present=[(row,float(getattr(row,field))) for row in rows if getattr(row,field) is not None]
            if not present:
                panels.append({'label':label,'points':[]});continue
            low=min(value for row,value in present);high=max(value for row,value in present)
            padding=max((high-low)*.1,1);low-=padding;high+=padding
            points=[{'x':round(70+((row.observed_at-start).total_seconds()/seconds)*600,2),'y':round(180-(value-low)/(high-low)*140,2),'value':value,'record':row.pk,'when':timezone.localtime(row.observed_at)} for row,value in present]
            panels.append({'label':label,'unit':unit,'points':points,'low':round(low,1),'high':round(high,1),'start':timezone.localtime(start),'end':timezone.localtime(end)})
    return render(request,'operations/labour_trends.html',{'pregnancy':pregnancy,'patient':pregnancy.patient,'panels':panels,'rows':rows,'total':total})
