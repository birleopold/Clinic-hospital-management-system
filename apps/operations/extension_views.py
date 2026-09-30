from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.models import Facility
from apps.demographics.models import Patient
from common.facility_scope import filter_by_facility
from . import extension_services as s
from .models import (SpecimenCustody, SpecimenAliquot, ReagentLot, LaboratoryQC,
    LabRunEvidence, ProgrammeDefinition, ProgrammeEnrollment, ProgrammeReview, ImagingStudy,
    ContactPreference, Reminder)
from .outreach_services import actor_allowed, set_preference, retry

# Explicit fields and scope paths; never expose arbitrary model fields or relations.
REGISTERS = {
    'custody': (SpecimenCustody, 'Specimen custody', ['specimen','event','from_location','to_location','receiver','condition','reference','occurred_at'], 'specimen__order__patient__facility_id', ('admin','lab')),
    'aliquots': (SpecimenAliquot, 'Specimen aliquots', ['parent','quantity','unit','reason'], 'parent__order__patient__facility_id', ('admin','lab')),
    'reagents': (ReagentLot, 'Reagent lots', ['facility','name','lot_number','expires_on','opened_on','use_by'], 'facility_id', ('admin','lab')),
    'quality': (LaboratoryQC, 'Laboratory quality control', ['facility','asset','reagent','procedure_reference','control_lot','observations','outcome','valid_until'], 'facility_id', ('admin','lab')),
    'runs': (LabRunEvidence, 'Laboratory run evidence', ['worksheet','qc','run_at','reference'], 'worksheet__result__order__patient__facility_id', ('admin','lab')),
    'programmes': (ProgrammeDefinition, 'Clinical programme definitions', ['facility','name','version','clinical_owner','source_reference','protocol'], 'facility_id', ('admin','clinician')),
    'enrollments': (ProgrammeEnrollment, 'Patient programme enrollments', ['patient','programme','clinician','eligibility_evidence','consent_reference','enrolled_on','next_review'], 'patient__facility_id', ('admin','clinician','nurse')),
    'reviews': (ProgrammeReview, 'Programme review notes', ['enrollment','occurred_on','findings','plan','next_review','amends'], 'enrollment__patient__facility_id', ('admin','clinician','nurse')),
    'studies': (ImagingStudy, 'Imaging study registry', ['order','study_uid','accession','modality','performed_at','viewer_url','reference'], 'order__patient__facility_id', ('admin','clinician','radiology')),
}
RELATION_SCOPE = {
    'facility': 'pk', 'patient': 'facility_id', 'specimen': 'order__patient__facility_id', 'parent': 'order__patient__facility_id',
    'asset':'facility_id', 'reagent':'facility_id', 'worksheet':'result__order__patient__facility_id', 'qc':'facility_id',
    'clinical_owner':'staff_profile__facility_id', 'clinician':'staff_profile__facility_id', 'programme':'facility_id',
    'enrollment':'patient__facility_id', 'amends':'enrollment__patient__facility_id', 'order':'patient__facility_id',
}


def config(actor, kind):
    from django.http import Http404
    if kind not in REGISTERS:
        raise Http404
    cfg = REGISTERS[kind]
    s.role(actor, cfg[4])
    return cfg


def form_for(model, fields, actor, data=None):
    widgets = {}
    for name in fields:
        field = model._meta.get_field(name)
        if field.get_internal_type() == 'DateTimeField':
            widgets[name] = forms.DateTimeInput(attrs={'type':'datetime-local'}, format='%Y-%m-%dT%H:%M')
        elif field.get_internal_type() == 'DateField':
            widgets[name] = forms.DateInput(attrs={'type':'date'})
    form = forms.modelform_factory(model, fields=fields, widgets=widgets)(data)
    for name, field in form.fields.items():
        if name in RELATION_SCOPE:
            field.queryset = filter_by_facility(field.queryset, actor, RELATION_SCOPE[name])
        if name in ('clinical_owner','clinician'):
            field.queryset = field.queryset.filter(is_active=True, role='clinician')
        elif name == 'patient':
            field.queryset = field.queryset.filter(merged_into__isnull=True)
        elif name == 'programme':
            field.queryset = field.queryset.filter(status='published')
        elif name == 'order':
            field.queryset = field.queryset.filter(order_type='imaging').exclude(status='cancelled')
    for name in ('specimen','parent'):
        if name in form.fields:
            field=form.fields[name]
            field.queryset=field.queryset.select_related('order__patient')
            field.label_from_instance=lambda obj: f'{obj.accession} · {obj.order.patient} · {obj.specimen_type} · {obj.get_status_display()}'
    if 'worksheet' in form.fields:
        form.fields['worksheet'].queryset=form.fields['worksheet'].queryset.select_related('result__order__patient')
        form.fields['worksheet'].label_from_instance=lambda obj: f'Worksheet #{obj.pk} · {obj.result.order.patient} · {obj.result.order.code}'
    if 'qc' in form.fields:
        form.fields['qc'].queryset=form.fields['qc'].queryset.select_related('reagent')
        form.fields['qc'].label_from_instance=lambda obj: f'QC #{obj.pk} · {obj.reagent} · {obj.get_outcome_display()} · valid until {obj.valid_until}'
    if 'order' in form.fields:
        form.fields['order'].queryset=form.fields['order'].queryset.select_related('patient')
        form.fields['order'].label_from_instance=lambda obj: f'Order #{obj.pk} · {obj.patient} · {obj.code}'
    return form


@login_required
def register(request, kind):
    model, title, fields, scope, roles = config(request.user, kind)
    qs = filter_by_facility(model.objects.all(), request.user, scope).order_by('-pk')
    if kind == 'enrollments' and request.GET.get('status') in ('active','completed','transferred','withdrawn'):
        qs = qs.filter(status=request.GET['status'])
    relations = ['created_by'] + [name for name in fields if model._meta.get_field(name).is_relation]
    qs=qs.select_related(*relations)
    page = Paginator(qs, 20).get_page(request.GET.get('page'))
    visible = list(fields)
    extras = {
        'aliquots':['child'], 'reagents':['quarantined','reviewed_by','reviewed_at','review_reason'],
        'quality':['reviewed_by','reviewed_at','review_reason'], 'programmes':['status','reviewed_by','reviewed_at'],
        'enrollments':['status','protocol_snapshot','closure_reason'],
    }
    visible += extras.get(kind, [])
    rows = []
    for obj in page:
        values = [(model._meta.get_field(name).verbose_name, getattr(obj, name)) for name in visible]
        rows.append((obj, values))
    from common.service_policy import enabled,service_for_url
    links = [(key, cfg[1]) for key,cfg in REGISTERS.items() if (request.user.is_superuser or request.user.role in cfg[4]) and enabled(request.user,service_for_url('/suite/clinical-operations/'+key+'/'))]
    return render(request, 'operations/extension_register.html', {'title':title,'kind':kind,'rows':rows,'page':page,'links':links,'status':request.GET.get('status',''),'can_review':request.user.is_superuser or request.user.role!='nurse','can_create':not(kind=='enrollments' and request.user.role=='nurse' and not request.user.is_superuser)})


@login_required
def create(request, kind):
    model,title,fields,scope,roles = config(request.user,kind)
    if kind == 'enrollments':
        s.role(request.user, ('admin','clinician'))
    form = form_for(model, fields, request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = dict(form.cleaned_data)
        try:
            if kind == 'custody': s.custody(data.pop('specimen').pk, request.user, **data)
            elif kind == 'aliquots': s.aliquot(data.pop('parent').pk, request.user, **data)
            elif kind == 'reagents': s.reagent_create(request.user, **data)
            elif kind == 'quality': s.qc_create(request.user, **data)
            elif kind == 'runs': s.attach_run(data.pop('worksheet').pk, request.user, **data)
            elif kind == 'programmes': s.programme_create(request.user, **data)
            elif kind == 'enrollments': s.enroll(request.user, **data)
            elif kind == 'reviews': s.programme_visit(data.pop('enrollment').pk, request.user, **data)
            elif kind == 'studies': s.imaging_create(request.user, **data)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
        else:
            return redirect('suite-extension', kind=kind)
    return render(request, 'operations/workflow_form.html', {'title':f'Add: {title}','form':form,'help':'Record the approved source and actual observations. Records are retained for audit; use a new referenced entry for corrections. Dates and times use the facility application timezone.'})


@login_required
@require_POST
def action(request, kind, pk):
    model,title,fields,scope,roles = config(request.user,kind)
    get_object_or_404(filter_by_facility(model.objects.all(), request.user, scope), pk=pk)
    decision,reason = request.POST.get('decision',''),request.POST.get('reason','')[:250]
    try:
        if kind == 'reagents':
            if decision not in ('release','quarantine'): raise ValidationError('Unknown reagent action.')
            s.reagent_review(pk,request.user,decision=='release',reason)
        elif kind == 'quality': s.qc_review(pk,request.user,reason)
        elif kind == 'programmes': s.programme_review(pk,request.user,decision,reason)
        elif kind == 'enrollments': s.programme_close(pk,request.user,decision,reason)
        else: raise ValidationError('This record is append-only.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    else:
        messages.success(request, 'Review recorded.')
    return redirect('suite-extension',kind=kind)


@login_required
def outreach(request):
    actor_allowed(request.user)
    class Form(forms.Form):
        patient=forms.ModelChoiceField(queryset=filter_by_facility(Patient.objects.filter(merged_into__isnull=True),request.user))
        sms_allowed=forms.BooleanField(required=False,label='Patient explicitly permits SMS follow-up')
        verified_phone=forms.CharField(max_length=20,required=False)
        evidence=forms.CharField(max_length=250,label='Consent / opt-out evidence and recipient authority')
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        try: set_preference(data['patient'].pk,request.user,data['sms_allowed'],data['verified_phone'],data['evidence'])
        except ValidationError as exc: form.add_error(None,'; '.join(exc.messages))
        else: return redirect('suite-outreach')
    rows=filter_by_facility(Reminder.objects.select_related('patient').prefetch_related('delivery_attempts'),request.user,'patient__facility_id').order_by('-pk')
    preferences=filter_by_facility(ContactPreference.objects.select_related('patient'),request.user,'patient__facility_id').order_by('-updated_at')[:25]
    return render(request,'operations/outreach.html',{'form':form,'page':Paginator(rows,25).get_page(request.GET.get('page')),'preferences':preferences})


@login_required
@require_POST
def outreach_retry(request,pk):
    actor_allowed(request.user)
    get_object_or_404(filter_by_facility(Reminder.objects.all(),request.user,'patient__facility_id'),pk=pk)
    try: retry(pk,request.user)
    except ValidationError as exc: messages.error(request,'; '.join(exc.messages))
    return redirect('suite-outreach')
