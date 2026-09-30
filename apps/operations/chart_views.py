"""Read-only patient chart built from original records, with explicit role sections."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Value, CharField, F
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from common.facility_scope import filter_by_facility
from apps.demographics.models import Patient
from apps.encounters.models import Encounter, Vital
from apps.pharmacy.models import Prescription
from apps.orders.models import OrderResult
from .models import ClinicalEntry, Referral, OfflineReceipt, ConsultationNote, PatientDocument, CarePlan, TheatreCase, Pregnancy, Vaccination, RehabilitationPlan, VisitingCaseNote
from apps.billing.models import Invoice


@login_required
@never_cache
def patient_chart(request, pk):
    user = request.user
    if not user.is_active or not (user.is_superuser or user.role in ('admin','clinician','nurse','pharmacy','lab','reception','cashier','manager')):
        raise PermissionDenied
    patient = get_object_or_404(filter_by_facility(Patient.objects.all(), user), pk=pk)
    if patient.merged_into_id:
        return redirect('suite-patient', pk=patient.merged_into_id)
    clinical = user.is_superuser or user.role in ('admin','clinician','nurse')
    laboratory = user.is_superuser or user.role in ('admin','lab')
    # Limited roles get only their work-relevant sections, including on direct URLs.
    sources = {}
    financial=user.is_superuser or user.role in ('admin','cashier','manager')
    if financial:sources['billing']=(Invoice.objects.filter(patient=patient),'created_at','Billing')
    if user.role=='reception' and not user.is_superuser:
        from apps.appointments.models import Appointment
        sources['appointments']=(Appointment.objects.filter(patient=patient),'scheduled_for','Appointments')

    if clinical:
        sources['visitingnotes']=(VisitingCaseNote.objects.filter(engagement__case__patient=patient),'created_at','Visiting specialist notes')
        sources['consultations']=(ConsultationNote.objects.filter(patient=patient),'created_at','Consultation notes')
        sources['documents']=(PatientDocument.objects.filter(patient=patient),'created_at','Documents')
        sources['careplans']=(CarePlan.objects.filter(admission__patient=patient),'created_at','Care plans')
        for key,model,label in [('theatre',TheatreCase,'Theatre'),('maternity',Pregnancy,'Maternity'),('vaccinations',Vaccination,'Vaccinations'),('rehabilitation',RehabilitationPlan,'Rehabilitation')]:
            sources[key]=(model.objects.filter(patient=patient),'created_at',label)
        sources['visits'] = (Encounter.objects.filter(patient=patient), 'started_at', 'Visits')
        sources['notes'] = (ClinicalEntry.objects.filter(patient=patient), 'created_at', 'Clinical notes')
        sources['vitals'] = (Vital.objects.filter(encounter__patient=patient), 'taken_at', 'Vitals')
        sources['referrals'] = (Referral.objects.filter(patient=patient), 'created_at', 'Referrals')
    if clinical or user.role == 'pharmacy':
        sources['medicines'] = (Prescription.objects.filter(patient=patient), 'created_at', 'Prescriptions')
        if not clinical:
            sources['allergies'] = (ClinicalEntry.objects.filter(patient=patient,kind='allergy'), 'created_at', 'Allergy history')
    if clinical or laboratory:
        results = OrderResult.objects.filter(order__patient=patient)
        if not laboratory:
            results = results.filter(approved_at__isnull=False)
        sources['results'] = (results, 'recorded_at', 'Results')
    section = request.GET.get('section', 'timeline')
    if section != 'timeline' and section not in sources:
        raise PermissionDenied
    visit_id = request.GET.get('visit', '')
    visit = None
    if visit_id:
        if not clinical or not visit_id.isdigit():
            raise PermissionDenied
        visit = get_object_or_404(Encounter, pk=visit_id, patient=patient)
    selected = {}
    for key, (qs, date_field, label) in sources.items():
        if section != 'timeline' and key != section:
            continue
        if visit:
            relation = {'visits':'pk','vitals':'encounter_id','medicines':'encounter_id','results':'order__encounter_id','consultations':'encounter_id','documents':'encounter_id'}.get(key)
            qs = qs.filter(**{relation:visit.pk}) if relation else qs.none()
        selected[key] = (qs, date_field, label)
    queries = [qs.order_by().annotate(event_kind=Value(key,output_field=CharField()),event_time=F(date)).values('event_kind','pk','event_time') for key,(qs,date,_) in selected.items()]
    feed = queries[0].union(*queries[1:], all=True).order_by('-event_time','event_kind','-pk')
    page = Paginator(feed, 25).get_page(request.GET.get('page'))
    metadata = list(page.object_list)
    objects = {}
    for key,(qs,_,_) in selected.items():
        ids = [row['pk'] for row in metadata if row['event_kind']==key]
        if key == 'visits': qs=qs.select_related('clinician').prefetch_related('diagnoses')
        elif key == 'results': qs=qs.select_related('order','recorded_by','approved_by')
        elif key in ('notes','allergies','referrals','consultations','documents','careplans','theatre','maternity','vaccinations','rehabilitation'): qs=qs.select_related('created_by')
        elif key == 'medicines': qs=qs.select_related('clinician').prefetch_related('items')
        objects[key] = {obj.pk:obj for obj in qs.filter(pk__in=ids)}
    events=[]
    for row in metadata:
        key=row['event_kind']; obj=objects[key][row['pk']]
        event={'kind':key,'obj':obj,'time':row['event_time'],'label':sources[key][2],'url':'','author':getattr(obj,'created_by',None),'offline_time':None}
        if key=='visits':
            event.update(title=f'Visit #{obj.pk} · {obj.get_status_display()}',text=obj.chief_complaint,author=obj.clinician,url=reverse('ehr-encounter-detail',args=[obj.pk]))
        elif key in ('notes','allergies'):
            event.update(title=obj.get_kind_display(),text=obj.text)
        elif key=='medicines':
            event.update(title=f'Prescription #{obj.pk}',text=obj.notes,author=obj.clinician)
            if user.is_superuser or user.role in ('admin','pharmacy','clinician'):event['url']=reverse('rx-detail',args=[obj.pk])
        elif key=='results':
            event.update(title=f'{obj.order.code} · {obj.analyte or "Result"}',text=obj.result_text,author=obj.recorded_by)
        elif key=='visitingnotes':
            event.update(title=f'Visiting case note #{obj.pk}',text=obj.body)
        elif key=='consultations':
            event.update(title=f'Consultation note #{obj.pk}',text=obj.body,url=reverse('suite-consultation-note',args=[obj.encounter_id])+f'?copy={obj.pk}')
        elif key=='documents':event.update(title=obj.title,text='',url=reverse('suite-document-download',args=[obj.pk]))
        elif key=='careplans':event.update(title=obj.problem,text=f'Goal: {obj.goal}\nIntervention: {obj.intervention}\nOutcome: {obj.outcome}',url=f'/suite/care-plans/?admission={obj.admission_id}')
        elif key=='billing':event.update(title=f'Invoice #{obj.pk} · {obj.get_status_display()}',text=f'Billed: {obj.total_amount} · Paid: {obj.paid_amount}',url=f'/cashier?patient={patient.pk}' if user.role!='manager' else '/reports')
        elif key=='appointments':event.update(title=f'Appointment · {obj.get_status_display()}',text=obj.reason_for_visit,url=f'/appointments/schedule?patient={patient.pk}')
        elif key in ('theatre','maternity','vaccinations','rehabilitation'):
            slug={'maternity':'pregnancies'}.get(key,key)
            event.update(title=f'{sources[key][2]} #{obj.pk}',text=str(obj),url=reverse('suite-specialty-detail',args=[slug,obj.pk]))
        elif key=='vitals':event.update(title='Recorded observations',text='')
        else:event.update(title=f'Referral · {obj.destination}',text=obj.reason)
        events.append(event)
    # Receipt lookup is bounded to the displayed page and does not mix model IDs.
    for key in ('notes','allergies','referrals'):
        group=[e for e in events if e['kind']==key]
        if group:
            model=group[0]['obj']._meta.label_lower
            receipts=dict(OfflineReceipt.objects.filter(model_label=model,record_id__in=[e['obj'].pk for e in group]).values_list('record_id','client_created_at'))
            for e in group:e['offline_time']=receipts.get(e['obj'].pk)
    overview=[]
    if clinical:
        overview=[{'label':label,'count':qs.count(),'key':key} for key,(qs,_,label) in sources.items() if key in ('visits','documents','careplans','consultations')]
    return render(request,'operations/chart.html',{'overview':overview,'patient':patient,'financial':financial,'events':events,'page':page,'section':section,'sections':[(k,v[2]) for k,v in sources.items()],'clinical':clinical,'laboratory':laboratory,'selected_visit':visit,'chart_visits':Encounter.objects.filter(patient=patient).order_by('-started_at')[:100] if clinical else [],'active_visits':Encounter.objects.filter(patient=patient,status='open').order_by('-started_at')[:5] if clinical else []})


@login_required
@never_cache
def patient_search(request):
    user=request.user
    if not user.is_active or not (user.is_superuser or user.role in ('admin','clinician','nurse','pharmacy','lab','reception','cashier','manager')):
        raise PermissionDenied
    from django.db.models import Q
    import uuid
    query=request.GET.get('q','').strip()[:120]
    patients=Patient.objects.none()
    if len(query)>=2:
        names=Q()
        for part in query.split():
            names &= Q(first_name__icontains=part)|Q(last_name__icontains=part)
        condition=names|Q(phone__icontains=query)
        try:condition |= Q(medical_record_id=uuid.UUID(query))
        except ValueError:pass
        patients=filter_by_facility(Patient.objects.filter(merged_into__isnull=True),user).filter(condition).order_by('last_name','first_name','pk')
    return render(request,'operations/chart_search.html',{'query':query,'page':Paginator(patients,25).get_page(request.GET.get('page'))})
