from datetime import timedelta, datetime, date
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Sum, Q
from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from common.facility_scope import filter_by_facility, filter_by_patient_facility
from apps.demographics.models import Patient
from apps.accounts.models import User
from apps.appointments.models import Appointment
from apps.encounters.models import Encounter
from apps.orders.models import Order, OrderResult
from apps.pharmacy.models import PrescriptionItem
from apps.inventory.models import Batch
from apps.billing.models import Payment, Invoice
from .models import ClinicalEntry, Referral, Specimen, StockLocation, StockCount, Refund, Bed, Admission, NursingObservation, MedicationAdministration, Payer, Claim, PortalGrant, Reminder, DuplicateReview, ServiceRoom, InvoiceCredit
from .models import PatientMerge, LabPanel, LabAnalyte, InpatientOrder, CarePlan, PackageUnit, SupplierCredit, CoveragePlan, Policy, Remittance, PaymentIntent
from apps.inventory.models import InventoryItem, Supplier, PurchaseOrder
from .advanced_services import merge_patients, prepare_claim, post_remittance, scheduled_doses
from .specialty_services import SPECIALTIES, create_specialty, transition_specialty
from .care_services import CARE_RECORDS, create_care_record, review_care_record
from .models import VaccinationAdverseEvent, VaccinationCorrection, StorageProtocol, ColdChainReading, PerioperativeEntry, InstrumentCount, Delivery, Newborn, LabourObservation, RehabilitationOutcome
from .models import TheatreCase, Pregnancy, MaternityVisit, Vaccination, RehabilitationPlan, RehabilitationSession
from .services import post_count, approve_refund, transfer_stock, approve_credit

# Every collection and writable relation has an explicit scope and role policy.
MODULES = {
 'vaccine-adverse-events': (VaccinationAdverseEvent, 'Suspected vaccine adverse events', ['vaccination','occurred_at','description','seriousness','action_taken','follow_up_on','reporting_reference'], 'vaccination__patient__facility_id', ['clinician','nurse']),
 'vaccination-corrections': (VaccinationCorrection, 'Vaccination corrections', ['vaccination','field_name','corrected_value','reason'], 'vaccination__patient__facility_id', ['clinician','nurse']),
 'storage-protocols': (StorageProtocol, 'Storage protocols', ['facility','name','lower_c','upper_c','source_reference'], 'facility_id', ['store','manager']),
 'cold-chain': (ColdChainReading, 'Cold-chain readings', ['batch','protocol','measured_at','temperature_c','device_reference','note'], 'batch__location__facility_id', ['store','manager','nurse','pharmacy']),
 'perioperative': (PerioperativeEntry, 'Anesthesia & theatre observations', ['case','occurred_at','kind','findings','intervention','plan','supersedes','amendment_reason'], 'case__patient__facility_id', ['clinician','nurse']),
 'instrument-counts': (InstrumentCount, 'Theatre instrument counts', ['case','phase','item_group','expected','counted','discrepancy_note'], 'case__patient__facility_id', ['clinician','nurse']),
 'deliveries': (Delivery, 'Delivery records', ['pregnancy','occurred_at','mode','maternal_condition','complications','care_provided','follow_up_plan'], 'pregnancy__patient__facility_id', ['clinician','nurse']),
 'newborns': (Newborn, 'Newborn records', ['delivery','patient','birth_order','outcome','birth_weight_kg','apgar_1_min','apgar_5_min','notes'], 'delivery__pregnancy__patient__facility_id', ['clinician','nurse']),
 'labour-observations': (LabourObservation, 'Labour observations', ['pregnancy','observed_at','fetal_heart_rate','cervical_dilation_cm','contractions_per_10_min','maternal_pulse','systolic','diastolic','temperature_c','findings','plan','supersedes','amendment_reason'], 'pregnancy__patient__facility_id', ['clinician','nurse']),
 'rehab-outcomes': (RehabilitationOutcome, 'Rehabilitation outcomes', ['plan','measured_at','instrument_name','instrument_version','source_reference','score','units','interpretation'], 'plan__patient__facility_id', ['clinician','nurse']),
 'theatre': (TheatreCase, 'Theatre scheduling', ['patient','room','surgeon','procedure','indication','starts_at','ends_at'], 'patient__facility_id', ['clinician','nurse']),
 'pregnancies': (Pregnancy, 'Maternity episodes', ['patient','gravida','parity','last_menstrual_period','estimated_due_date','assessment'], 'patient__facility_id', ['clinician','nurse']),
 'maternity-visits': (MaternityVisit, 'Maternity visits & amendments', ['pregnancy','occurred_at','visit_type','findings','care_provided','plan','follow_up_on','supersedes','amendment_reason'], 'pregnancy__patient__facility_id', ['clinician','nurse']),
 'vaccinations': (Vaccination, 'Vaccination visits', ['patient','vaccine','dose_label','due_on','stock_source','source_reference','stock_batch','stock_quantity'], 'patient__facility_id', ['clinician','nurse']),
 'rehabilitation': (RehabilitationPlan, 'Rehabilitation care plans', ['patient','clinician','problem','baseline','goals','intervention_plan','review_on'], 'patient__facility_id', ['clinician','nurse']),
 'rehab-sessions': (RehabilitationSession, 'Rehabilitation sessions', ['plan','occurred_at','intervention','response','progress','next_visit_on','supersedes','amendment_reason'], 'plan__patient__facility_id', ['clinician','nurse']),
 'lab-panels': (LabPanel, 'Laboratory panels', ['facility','code','name','specimen_type','active'], 'facility_id', ['lab','manager']),
 'lab-analytes': (LabAnalyte, 'Analytes & approved ranges', ['panel','code','name','units','low','high','reference_note'], 'panel__facility_id', ['lab','manager']),
 'inpatient-orders': (InpatientOrder, 'Inpatient medication orders', ['admission','prescription_item','dose','route','interval_hours','starts_at','ends_at'], 'admission__patient__facility_id', ['clinician']),
 'care-plans': (CarePlan, 'Nursing care plans', ['admission','problem','goal','intervention','review_at'], 'admission__patient__facility_id', ['nurse','clinician']),
 'packages': (PackageUnit, 'Packaging & units', ['item','name','units_per_pack'], None, ['store','manager','pharmacy']),
 'supplier-credits': (SupplierCredit, 'Supplier credit reconciliation', ['facility','supplier','reference','amount','reason','applied_po'], 'facility_id', ['store','manager']),
 'coverage': (CoveragePlan, 'Coverage rules', ['payer','name','service_code','covered_percent','requires_authorization','valid_from','valid_until'], 'payer__facility_id', ['manager']),
 'policies': (Policy, 'Patient insurance eligibility', ['patient','payer','membership_number','valid_from','valid_until','verification_reference'], 'patient__facility_id', ['cashier','manager']),
 'remittances': (Remittance, 'Payer remittances', ['claim','reference','amount'], 'claim__invoice__patient__facility_id', ['cashier','manager']),
 'collections': (PaymentIntent, 'Mobile-money collections', ['invoice','amount','phone'], 'invoice__patient__facility_id', ['cashier','manager']),
 'credits': (InvoiceCredit, 'Invoice credits', ['invoice','amount','reason'], 'invoice__patient__facility_id', ['cashier','manager']),
 'rooms': (ServiceRoom, 'Service rooms', ['facility','name'], 'facility_id', ['manager','reception']),
 'bookings': (Appointment, 'Appointment bookings', ['patient','clinician','room','appointment_type','scheduled_for','duration_minutes','reason_for_visit'], 'patient__facility_id', ['reception','clinician']),
 'reminders': (Reminder, 'Reminder outbox', ['patient','scheduled_for','body','consent_confirmed'], 'patient__facility_id', ['reception','manager']),
 'duplicates': (DuplicateReview, 'Duplicate identity review', ['patient','candidate','reason'], 'patient__facility_id', ['reception','manager']),
 'clinical': (ClinicalEntry, 'Clinical history', ['patient','kind','text','supersedes'], 'patient__facility_id', ['clinician','nurse']),
 'referrals': (Referral, 'Referrals & follow-up', ['patient','destination','reason','due_date'], 'patient__facility_id', ['clinician','nurse']),
 'specimens': (Specimen, 'Specimen tracking', ['order','specimen_type'], 'order__patient__facility_id', ['lab','clinician']),
 'results': (OrderResult, 'Results & approval', ['order','specimen','catalog_analyte','supersedes','analyte','value','units','reference_range','result_text','attachment','critical'], 'order__patient__facility_id', ['lab','clinician']),
 'locations': (StockLocation, 'Stock locations', ['facility','name'], 'facility_id', ['store','manager','pharmacy']),
 'counts': (StockCount, 'Stock counts', ['batch','counted','reason'], 'batch__location__facility_id', ['store','manager','pharmacy']),
 'refunds': (Refund, 'Refund requests', ['payment','amount','reason'], 'payment__invoice__patient__facility_id', ['cashier','manager']),
 'beds': (Bed, 'Wards & beds', ['facility','ward','name','active'], 'facility_id', ['nurse','manager','clinician']),
 'admissions': (Admission, 'Admissions', ['patient','bed','reason'], 'patient__facility_id', ['nurse','clinician']),
 'observations': (NursingObservation, 'Nursing observations', ['admission','observations'], 'admission__patient__facility_id', ['nurse','clinician']),
 'administrations': (MedicationAdministration, 'Medication administration', ['admission','prescription_item','scheduled_for','outcome','dose','notes'], 'admission__patient__facility_id', ['nurse','clinician']),
 'payers': (Payer, 'Payer directory', ['facility','name','contact'], 'facility_id', ['cashier','manager']),
 'claims': (Claim, 'Insurance claims', ['invoice','payer','membership_number','authorization_reference','amount'], 'invoice__patient__facility_id', ['cashier','manager']),
}
RELATIONS = {
 Vaccination:'patient__facility_id', StorageProtocol:'facility_id', TheatreCase:'patient__facility_id',
 PerioperativeEntry:'case__patient__facility_id', Delivery:'pregnancy__patient__facility_id', LabourObservation:'pregnancy__patient__facility_id',
 Pregnancy:'patient__facility_id', MaternityVisit:'pregnancy__patient__facility_id',
 RehabilitationPlan:'patient__facility_id', RehabilitationSession:'plan__patient__facility_id',
 LabPanel:'facility_id', LabAnalyte:'panel__facility_id', Specimen:'order__patient__facility_id',
 Policy:'patient__facility_id', Claim:'invoice__patient__facility_id', PurchaseOrder:'facility_id',

 User: 'staff_profile__facility_id', ServiceRoom: 'facility_id',
 Patient: 'facility_id', Encounter: 'facility_id', Order: 'patient__facility_id',
 OrderResult: 'order__patient__facility_id', ClinicalEntry: 'patient__facility_id', Batch: 'location__facility_id',
 Payment: 'invoice__patient__facility_id', Invoice: 'patient__facility_id',
 Bed: 'facility_id', Admission: 'patient__facility_id', Payer: 'facility_id',
 PrescriptionItem: 'prescription__patient__facility_id',
}

def display_value(value):
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime('%d %b %Y, %H:%M %Z') if timezone.is_aware(value) else value.strftime('%d %b %Y, %H:%M')
    if isinstance(value, date):
        return value.strftime('%d %b %Y')
    return '—' if value is None or value == '' else str(value)


def allowed(user, roles):
    return user.is_active and (user.is_superuser or user.role == 'admin' or user.role in roles)

def config(request, slug):
    if slug not in MODULES:
        raise Http404
    conf = MODULES[slug]
    if not allowed(request.user, conf[4]):
        raise PermissionDenied
    return conf

def scoped(model, user, field):
    if field is None:
        return model.objects.all() if allowed(user,['store','manager','pharmacy']) else model.objects.none()
    qs=filter_by_facility(model.objects.all(), user, field=field)
    if model in (Order,OrderResult):
        from common.service_policy import enabled
        prefix='order__' if model is OrderResult else ''
        if not enabled(user,'lab'):qs=qs.exclude(**{prefix+'order_type':'lab'})
        if not enabled(user,'imaging'):qs=qs.exclude(**{prefix+'order_type':'imaging'})
        if not enabled(user,'clinical'):qs=qs.exclude(**{prefix+'order_type':'procedure'})
    return qs

@login_required
def workspace(request):
    from common.service_policy import enabled, SLUG_SERVICES, service_for_url, navigation, can_open
    links = [{'slug':key,'label':conf[1]} for key,conf in MODULES.items() if allowed(request.user,conf[4]) and enabled(request.user,SLUG_SERVICES.get(key))]
    from .workspaces import workspace_context
    context = workspace_context(request.user)
    context['modules'] = links
    context['role_actions']=[a for a in context['role_actions'] if can_open(request.user,a['url'])]
    context['attention_cards']=[a for a in context['attention_cards'] if can_open(request.user,a['url'])]
    context['show_visits']=context['show_visits'] and enabled(request.user,'clinical')
    context['service_workspaces']=navigation(request.user)
    return render(request,'operations/home.html',context)


def collection_form(request, model, fields):
    Form = forms.modelform_factory(model,fields=fields)
    form = Form(request.POST or None,request.FILES or None)
    for name,field in form.fields.items():
        field.widget.attrs['class'] = 'field-control'
        if isinstance(field,forms.DateTimeField):
            field.widget = forms.DateTimeInput(attrs={'type':'datetime-local'})
        elif isinstance(field,forms.DateField):
            field.widget = forms.DateInput(attrs={'type':'date'})
        if isinstance(field,forms.ModelChoiceField):
            related = field.queryset.model
            if related.__name__ == 'Facility':
                field.queryset = filter_by_facility(field.queryset,request.user,field='pk')
            elif related in (InventoryItem,Supplier):
                field.queryset = field.queryset.all()
            elif related in RELATIONS:
                field.queryset = scoped(related,request.user,RELATIONS[related])
            else:
                field.queryset = field.queryset.none()
            if related is Patient:
                field.queryset = field.queryset.filter(merged_into__isnull=True)
                field.label_from_instance = lambda p: f'{p} · {str(p.medical_record_id)[:8]}'
            if related is User:
                field.queryset = field.queryset.filter(role='clinician',is_active=True)
            if related is Bed:
                field.queryset = field.queryset.filter(active=True).exclude(admission__discharged_at__isnull=True,admission__isnull=False)
            if related is Admission:
                field.queryset = field.queryset.filter(discharged_at__isnull=True)
            if related is Order:
                field.queryset = field.queryset.exclude(status='cancelled')
    if request.method == 'GET':
        for name, field in form.fields.items():
            if isinstance(field, forms.ModelChoiceField) and request.GET.get(name):
                try: selected = field.queryset.get(pk=request.GET[name])
                except (ValueError, field.queryset.model.DoesNotExist): raise Http404
                form.initial[name] = selected.pk
    # Limit HTML option payloads without weakening the complete validation queryset.
    slug = request.resolver_match.kwargs.get('slug') if request.resolver_match else None
    if slug and not request.path.startswith(('/offline/','/suite/lookup/')):
        for name, field in form.fields.items():
            if isinstance(field, forms.ModelChoiceField):
                selected = form.data.get(name) if form.is_bound else form.initial.get(name)
                initial_options = list(field.queryset.order_by('-pk')[:30])
                if selected:
                    try:
                        obj = field.queryset.filter(pk=selected).first()
                        if obj and all(x.pk != obj.pk for x in initial_options): initial_options.insert(0,obj)
                    except (ValueError, TypeError): pass
                field.widget.choices = [('', 'Choose an option')] + [(o.pk,field.label_from_instance(o)) for o in initial_options]
                field.widget.attrs['data-lookup'] = reverse('suite-lookup',args=[slug,name])
    return form


@transaction.atomic
def save_collection_form(form, user):
    obj = form.save(commit=False)
    if hasattr(obj,'created_by_id'):
        obj.created_by = user
    if isinstance(obj,Reminder) and (not obj.consent_confirmed or not obj.patient.phone):
        raise ValidationError('Record consent and a patient phone number before scheduling a reminder.')
    if isinstance(obj,DuplicateReview) and (obj.patient_id==obj.candidate_id or obj.patient.facility_id!=obj.candidate.facility_id):
        raise ValidationError('Choose two different patient records in the same facility.')
    if isinstance(obj,ClinicalEntry) and obj.supersedes_id and obj.supersedes.patient_id != obj.patient_id:
        raise ValidationError('Amendments must belong to the same patient.')
    if isinstance(obj,OrderResult):
        obj.recorded_by=user
        if obj.supersedes_id and (obj.supersedes.order_id!=obj.order_id or not obj.supersedes.approved_at):
            raise ValidationError('Amendments must reference a released result for the same order.')
    if isinstance(obj,StockCount):
        obj.batch = Batch.objects.select_for_update().get(pk=obj.batch_id)
        obj.expected = obj.batch.quantity_on_hand
        if obj.counted < 0:
            raise ValidationError('Count cannot be negative.')
    if isinstance(obj,InvoiceCredit) and (obj.amount<=0 or obj.amount>obj.invoice.total_amount):
        raise ValidationError('Enter a positive credit within the invoice total.')
    if isinstance(obj,Refund) and (obj.amount <= 0 or obj.amount > obj.payment.amount):
        raise ValidationError('Enter a positive amount within the original payment.')
    if isinstance(obj,Admission):
        obj.bed = Bed.objects.select_for_update().get(pk=obj.bed_id)
        if obj.bed.facility_id != obj.patient.facility_id or not obj.bed.active:
            raise ValidationError('Choose an active bed in the patient facility.')
        if Admission.objects.filter(Q(bed=obj.bed)|Q(patient=obj.patient),discharged_at__isnull=True).exists():
            raise ValidationError('The bed or patient already has an active admission.')
    if isinstance(obj,(MedicationAdministration,NursingObservation)):
        admission=Admission.objects.select_for_update().get(pk=obj.admission_id)
        if admission.discharged_at: raise ValidationError('This admission is already discharged.')
    if isinstance(obj,MedicationAdministration):
        if obj.admission.patient_id != obj.prescription_item.prescription.patient_id:
            raise ValidationError('Prescription and admission must belong to the same patient.')
        if obj.scheduled_for > timezone.now() and obj.outcome == 'given':
            raise ValidationError('Cannot record a future dose as given.')
    if isinstance(obj,Claim):
        if obj.payer.facility_id != obj.invoice.patient.facility_id or obj.amount <= 0 or obj.amount > obj.invoice.total_amount:
            raise ValidationError('Choose a payer in the same facility and a valid invoice amount.')
    from .advanced_validation import validate_new_record
    validate_new_record(obj,user)
    if isinstance(obj, CARE_RECORDS):
        create_care_record(obj, user)
    elif isinstance(obj, SPECIALTIES):
        create_specialty(obj, user)
    else:
        obj.save()
    if isinstance(obj,Remittance): post_remittance(obj)
    if isinstance(obj,ClinicalEntry) and obj.kind == 'allergy':
        Patient.objects.filter(pk=obj.patient_id).update(allergy_status='recorded')
    return obj


@login_required
def collection(request, slug):
    model,title,fields,scope,roles = config(request,slug)
    form = collection_form(request, model, fields)
    if request.method == 'POST' and form.is_valid():
        try:
            saved=save_collection_form(form, request.user)
            messages.success(request,'Record saved.')
            from urllib.parse import urlencode
            context={name:form.cleaned_data[name].pk for name in ('patient','order','admission','pregnancy','vaccination','plan') if form.cleaned_data.get(name) is not None}
            return redirect(reverse('suite-collection',args=[slug])+('?' + urlencode(context) if context else ''))
        except (ValidationError,IntegrityError) as exc:
            form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'A conflicting record already exists. Refresh and try again.')
    from django.core.paginator import Paginator
    records = scoped(model,request.user,scope).order_by('-pk')
    if request.GET.get('record','').isdigit():records=records.filter(pk=int(request.GET['record']))
    for name, field in form.fields.items():
        if isinstance(field,forms.ModelChoiceField) and request.GET.get(name) and name in form.initial:
            records=records.filter(**{name+'_id':form.initial[name]})
    query=request.GET.get('q','').strip()
    if query:
        filters=Q()
        if scope and 'patient__' in scope:
            patient_prefix=scope.rsplit('facility_id',1)[0]
            filters |= Q(**{patient_prefix+'first_name__icontains':query}) | Q(**{patient_prefix+'last_name__icontains':query})
            import uuid
            try:
                identifier=uuid.UUID(query)
            except ValueError:
                pass
            else:
                filters |= Q(**{patient_prefix+'medical_record_id':identifier})
        for field in model._meta.fields:
            if isinstance(field,(model._meta.get_field('id').__class__,)) and query.isdigit(): filters |= Q(pk=int(query))
            if field.get_internal_type() in ('CharField','TextField'): filters |= Q(**{field.name+'__icontains':query})
        records=records.filter(filters)
    if any(f.name=='status' and f.choices for f in model._meta.fields):
        status = request.GET.get('status', '')
        if status in dict(model._meta.get_field('status').choices):
            records = records.filter(status=status)
    page=Paginator(records,25).get_page(request.GET.get('page'))
    records=page.object_list
    from .models import OfflineReceipt
    offline_times=dict(OfflineReceipt.objects.filter(model_label=model._meta.label_lower,record_id__in=[obj.pk for obj in records]).values_list('record_id','client_created_at'))
    rows=[]
    for obj in records:
        state = getattr(obj,'status','')
        if isinstance(obj,VaccinationCorrection): state = 'Applied' if obj.applied_at else 'Awaiting review'
        if isinstance(obj,StorageProtocol): state = 'Approved' if obj.approved_at else 'Awaiting approval'
        if isinstance(obj,InstrumentCount): state = 'Verified' if obj.verified_at else 'Awaiting second count review'
        if isinstance(obj,ColdChainReading): state = 'Excursion / quarantine' if obj.excursion else 'Within recorded limits'
        if isinstance(obj,OrderResult): state = 'Released' if obj.approved_at else 'Awaiting review'
        if isinstance(obj,Admission): state = 'Discharged' if obj.discharged_at else 'Admitted'
        values=[]
        for field in fields:
            if field == 'attachment':
                continue
            value=getattr(obj,field)
            values.append(display_value(value)[:180])
        rows.append({'obj':obj,'values':values,'state':state,'offline_at':offline_times.get(obj.pk)})
    return render(request,'operations/collection.html',{'specialty':model in SPECIALTIES + CARE_RECORDS,'page':page,'query':query,'title':title,'slug':slug,'form':form,'rows':rows,'available_beds':scoped(Bed,request.user,'facility_id').filter(active=True).exclude(admission__discharged_at__isnull=True,admission__isnull=False) if slug=='admissions' else [],'status_choices':model._meta.get_field('status').choices if any(f.name=='status' and f.choices for f in model._meta.fields) else [],'selected_status':request.GET.get('status',''),'headers':[model._meta.get_field(f).verbose_name for f in fields if f!='attachment']})

@login_required
@require_POST
def action(request,slug,pk,operation):
    model,title,fields,scope,roles=config(request,slug)
    try:
        with transaction.atomic():
            queryset=scoped(model,request.user,scope)
            if slug not in ('refunds','credits','reminders'):queryset=queryset.select_for_update()
            obj=get_object_or_404(queryset,pk=pk)
            if model in CARE_RECORDS:
                review_care_record(model,obj.pk,operation,request.POST,request.user)
            elif model in SPECIALTIES:
                transition_specialty(model, obj.pk, operation, request.POST, request.user)
            elif slug == 'duplicates' and operation == 'merge':
                merge_patients(obj.pk,request.user,request.POST.get('reason',''))
            elif slug == 'policies' and operation == 'verify':
                if not obj.verification_reference.strip(): raise ValidationError('Record eligibility evidence.')
                obj.verified_at=timezone.now();obj.save()
            elif slug == 'supplier-credits' and operation == 'reconcile':
                if not allowed(request.user,['manager']): raise PermissionDenied
                if not obj.applied_po_id: raise ValidationError('Link the purchase order before reconciliation.')
                if not obj.reconciled_at: obj.reconciled_at=timezone.now();obj.save()
            elif slug == 'inpatient-orders' and operation == 'stop':
                if not obj.stopped_at:
                    obj.stop_reason=request.POST.get('reason','').strip()
                    if not obj.stop_reason: raise ValidationError('A stop reason is required.')
                    obj.stopped_at=timezone.now();obj.save()
            elif slug == 'care-plans' and operation == 'complete':
                if not obj.completed_at:
                    obj.outcome=request.POST.get('reason','').strip()
                    if not obj.outcome: raise ValidationError('Record the care-plan outcome.')
                    obj.completed_at=timezone.now();obj.save()
            elif slug == 'bookings' and operation in ('confirmed','cancelled','no_show'):
                obj.status=operation;obj.save()
            elif slug == 'reminders' and operation == 'cancel':
                from apps.demographics.models import Patient
                patient=Patient.objects.select_for_update().get(pk=obj.patient_id)
                obj=Reminder.objects.select_for_update().get(pk=obj.pk)
                if obj.patient_id!=patient.pk:raise ValidationError('Patient identity changed; reload.')
                if obj.status not in ('pending','failed'): raise ValidationError('Only pending or failed reminders can be cancelled.')
                obj.status='cancelled';obj.save()
            elif slug == 'reminders' and operation == 'retry':
                from .outreach_services import retry
                retry(obj.pk,request.user)
            elif slug == 'duplicates' and operation in ('confirmed','distinct'):
                if not allowed(request.user,['manager']): raise PermissionDenied
                if obj.status != 'pending': raise ValidationError('This review is already complete.')
                obj.status=operation;obj.reviewed_by=request.user;obj.reviewed_at=timezone.now();obj.save()
            elif slug == 'counts' and operation == 'post':
                if not allowed(request.user,['manager']): raise PermissionDenied
                post_count(pk,request.user)
            elif slug == 'credits' and operation == 'approve':
                if not allowed(request.user,['manager']): raise PermissionDenied
                approve_credit(pk,request.user)
            elif slug == 'refunds' and operation == 'approve':
                if not allowed(request.user,['manager']): raise PermissionDenied
                approve_refund(pk,request.user)
            elif slug == 'results' and operation == 'release':
                if hasattr(obj, 'worksheet'):raise ValidationError('Review and release structured worksheets through the Diagnostics workspace.')
                if not allowed(request.user,['lab','clinician']): raise PermissionDenied
                if not obj.result_text.strip() and not obj.value.strip() and not obj.attachment:
                    raise ValidationError('A result needs content before release.')
                if obj.recorded_by_id == request.user.pk and not request.user.is_superuser:
                    raise ValidationError('A different reviewer must release this result.')
                if not obj.approved_at:
                    obj.approved_at=timezone.now();obj.approved_by=request.user;obj.save()
                    obj.order.status=Order.COMPLETED;obj.order.save(update_fields=['status'])
            elif slug == 'results' and operation == 'acknowledge':
                if not allowed(request.user,['clinician']): raise PermissionDenied
                if not obj.approved_at: raise ValidationError('Release the result first.')
                if not obj.acknowledged_at:
                    obj.acknowledged_at=timezone.now();obj.acknowledged_by=request.user;obj.save()
            elif slug == 'specimens' and operation in ('receive','reject'):
                if obj.status != 'collected': raise ValidationError('This specimen already has a final receiving decision.')
                obj.status='received' if operation=='receive' else 'rejected'
                obj.rejection_reason=request.POST.get('reason','').strip()
                if operation=='reject' and not obj.rejection_reason: raise ValidationError('A rejection reason is required.')
                obj.received_at=timezone.now();obj.save()
            elif slug == 'admissions' and operation == 'transfer':
                if obj.discharged_at: raise ValidationError('Already discharged.')
                bed=get_object_or_404(scoped(Bed,request.user,'facility_id').select_for_update(),pk=request.POST.get('bed'))
                if not bed.active or bed.facility_id!=obj.patient.facility_id:
                    raise ValidationError('Choose an active bed in the patient facility.')
                if Admission.objects.filter(bed=bed,discharged_at__isnull=True).exists():
                    raise ValidationError('That bed is occupied.')
                obj.bed=bed;obj.save()
            elif slug == 'admissions' and operation == 'discharge':
                if obj.discharged_at: raise ValidationError('Already discharged.')
                obj.discharge_summary=request.POST.get('reason','').strip()
                if not obj.discharge_summary: raise ValidationError('Enter a discharge summary.')
                obj.discharged_at=timezone.now();obj.save()
            elif slug == 'referrals' and operation in ('accepted','completed','cancelled'):
                permitted={'open':('accepted','cancelled'),'accepted':('completed','cancelled')}
                if operation not in permitted.get(obj.status,()): raise ValidationError('Invalid referral transition.')
                obj.status=operation
                if operation=='completed': obj.completed_at=timezone.now()
                obj.save()
            elif slug == 'claims' and operation in ('submitted','accepted','rejected'):
                permitted={'draft':('submitted',),'submitted':('accepted','rejected'),'rejected':('submitted',)}
                if operation not in permitted.get(obj.status,()): raise ValidationError('Invalid claim transition.')
                obj.response_note=request.POST.get('reason','').strip()
                if operation=='rejected' and not obj.response_note: raise ValidationError('Enter the payer rejection reason.')
                obj.status=operation;obj.save()
            else:
                raise Http404
        messages.success(request,'Action recorded.')
    except IntegrityError:
        messages.error(request, 'A conflicting update occurred. Refresh and review the record.')
    except ValidationError as exc:
        messages.error(request,'; '.join(exc.messages))
    if request.POST.get('return_to_record')=='1' and model in SPECIALTIES+CARE_RECORDS:
        return redirect('suite-specialty-detail',slug=slug,pk=pk)
    return redirect('suite-collection',slug=slug)

@login_required
def patient_summary(request,pk):
    if not allowed(request.user,['clinician','nurse']): raise PermissionDenied
    patient=get_object_or_404(filter_by_facility(Patient.objects.all(),request.user),pk=pk)
    if patient.merged_into_id: return redirect('suite-patient',pk=patient.merged_into_id)
    specialty_records = []
    if allowed(request.user, ['clinician','nurse']):
        for model, slug, label in [(TheatreCase,'theatre','Theatre'),(Pregnancy,'pregnancies','Maternity'),(Vaccination,'vaccinations','Vaccination'),(RehabilitationPlan,'rehabilitation','Rehabilitation')]:
            from common.service_policy import enabled, SLUG_SERVICES
            if not enabled(request.user,SLUG_SERVICES[slug]):continue
            specialty_records.append({'label':label,'slug':slug,'records':model.objects.filter(patient=patient).order_by('-pk')[:10]})
    return render(request,'operations/patient.html',{'specialty_records':specialty_records,'patient':patient,'entries':ClinicalEntry.objects.filter(patient=patient).select_related('created_by').order_by('-created_at'),'referrals':Referral.objects.filter(patient=patient).order_by('-created_at'),'grants':PortalGrant.objects.filter(patient=patient).order_by('-created_at')})

@login_required
def result_download(request,pk):
    if not allowed(request.user,['clinician','nurse','lab']): raise PermissionDenied
    result=get_object_or_404(scoped(OrderResult,request.user,'order__patient__facility_id'),pk=pk)
    if not result.attachment: raise Http404
    response=FileResponse(result.attachment.open('rb'),as_attachment=True,filename=result.attachment.name.rsplit('/',1)[-1])
    response['Cache-Control']='private, no-store'
    response['X-Content-Type-Options']='nosniff'
    return response

@login_required
@require_POST
def revoke_grant(request,pk):
    if not allowed(request.user,['clinician']): raise PermissionDenied
    grant=get_object_or_404(filter_by_patient_facility(PortalGrant.objects.all(),request.user),pk=pk)
    grant.revoked_at=timezone.now();grant.save(update_fields=['revoked_at'])
    messages.success(request,'Patient link revoked.')
    return redirect('suite-patient',pk=grant.patient_id)

@login_required
def stock_workspace(request):
    if not allowed(request.user,['store','manager','pharmacy']): raise PermissionDenied
    from apps.inventory.models import InventoryItem, StockMovement
    locations=scoped(StockLocation,request.user,'facility_id')
    batches=scoped(Batch,request.user,'location__facility_id')
    class StockForm(forms.Form):
        operation=forms.ChoiceField(choices=[('opening','Opening balance'),('transfer','Transfer'),('assign','Assign legacy batch'),('quarantine','Quarantine batch'),('release','Release quarantine'),('dispose','Dispose stock'),('return','Return to supplier')])
        batch=forms.ModelChoiceField(queryset=batches,required=False)
        item=forms.ModelChoiceField(queryset=InventoryItem.objects.all(),required=False)
        location=forms.ModelChoiceField(queryset=locations)
        package=forms.ModelChoiceField(queryset=PackageUnit.objects.all(),required=False,help_text='If selected, quantity is in packs. Balances are stored in base units.')
        quantity=forms.DecimalField(max_digits=12,decimal_places=2,min_value=Decimal('0.01'),required=False)
        batch_number=forms.CharField(max_length=64,required=False)
        expiry=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
        reason=forms.CharField(max_length=250)
    initial={}
    for field in ('batch','location'):
        value=request.GET.get(field,'')
        if value.isdigit() and StockForm.base_fields[field].queryset.filter(pk=value).exists():initial[field]=value
    if initial and request.GET.get('operation')=='transfer':initial['operation']='transfer'
    form=StockForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        try:
            with transaction.atomic():
                op=data['operation'];batch=data['batch'];location=data['location']
                if data['package']:
                    item_id=batch.item_id if batch else getattr(data['item'],'pk',None)
                    if item_id!=data['package'].item_id: raise ValidationError('Package does not match the item.')
                    if data['quantity'] is not None: data['quantity']*=data['package'].units_per_pack
                if op=='opening':
                    if not data['item'] or not data['quantity']: raise ValidationError('Item and quantity are required.')
                    batch=Batch.objects.create(item=data['item'],location=location,batch_no=data['batch_number'],expiry=data['expiry'],quantity_on_hand=data['quantity'])
                    StockMovement.objects.create(item=batch.item,batch=batch,direction='in',quantity=data['quantity'],reason=data['reason'][:64],ref=f'opening:user:{request.user.pk}')
                elif op=='transfer':
                    if not batch or not data['quantity']: raise ValidationError('Batch and quantity are required.')
                    transfer_stock(batch.pk,location,data['quantity'],request.user)
                else:
                    if not batch: raise ValidationError('Select a batch.')
                    batch=Batch.objects.select_for_update().get(pk=batch.pk)
                    if op in ('dispose','return'):
                        if not data['quantity'] or data['quantity']>batch.quantity_on_hand:
                            raise ValidationError('Enter a positive quantity within the batch balance.')
                        batch.quantity_on_hand-=data['quantity'];batch.save(update_fields=['quantity_on_hand'])
                        StockMovement.objects.create(item=batch.item,batch=batch,direction='out',quantity=data['quantity'],reason=data['reason'][:64],ref=f'{op}:user:{request.user.pk}')
                        messages.success(request,'Stock movement recorded.')
                        return redirect('suite-stock')
                    if op=='assign':
                        if not request.user.is_superuser or batch.location_id: raise ValidationError('Only a superuser can assign an unallocated legacy batch.')
                        batch.location=location
                    else:
                        if not allowed(request.user,['manager']): raise PermissionDenied
                        batch.quarantined=op=='quarantine'
                    batch.save()
                    StockMovement.objects.create(item=batch.item,batch=batch,direction='adjust',quantity=0,reason=data['reason'][:64],ref=f'{op}:user:{request.user.pk}')
            messages.success(request,'Stock operation recorded.')
            return redirect('suite-stock')
        except ValidationError as exc:
            form.add_error(None,'; '.join(exc.messages))
    return render(request,'operations/stock.html',{'form':form,'batches':batches.select_related('item','location').order_by('expiry')[:200]})
