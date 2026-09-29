from datetime import timedelta
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
from .services import post_count, approve_refund, transfer_stock, approve_credit

# Every collection and writable relation has an explicit scope and role policy.
MODULES = {
 'credits': (InvoiceCredit, 'Invoice credits', ['invoice','amount','reason'], 'invoice__patient__facility_id', ['cashier','manager']),
 'rooms': (ServiceRoom, 'Service rooms', ['facility','name'], 'facility_id', ['manager','reception']),
 'bookings': (Appointment, 'Appointment bookings', ['patient','clinician','room','appointment_type','scheduled_for','duration_minutes','reason_for_visit'], 'patient__facility_id', ['reception','clinician']),
 'reminders': (Reminder, 'Reminder outbox', ['patient','scheduled_for','body','consent_confirmed'], 'patient__facility_id', ['reception','manager']),
 'duplicates': (DuplicateReview, 'Duplicate identity review', ['patient','candidate','reason'], 'patient__facility_id', ['reception','manager']),
 'clinical': (ClinicalEntry, 'Clinical history', ['patient','kind','text','supersedes'], 'patient__facility_id', ['clinician','nurse']),
 'referrals': (Referral, 'Referrals & follow-up', ['patient','destination','reason','due_date'], 'patient__facility_id', ['clinician','nurse']),
 'specimens': (Specimen, 'Specimen tracking', ['order','specimen_type'], 'order__patient__facility_id', ['lab','clinician']),
 'results': (OrderResult, 'Results & approval', ['order','supersedes','analyte','value','units','reference_range','result_text','attachment','critical'], 'order__patient__facility_id', ['lab','clinician']),
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
 User: 'staff_profile__facility_id', ServiceRoom: 'facility_id',
 Patient: 'facility_id', Encounter: 'facility_id', Order: 'patient__facility_id',
 OrderResult: 'order__patient__facility_id', ClinicalEntry: 'patient__facility_id', Batch: 'location__facility_id',
 Payment: 'invoice__patient__facility_id', Invoice: 'patient__facility_id',
 Bed: 'facility_id', Admission: 'patient__facility_id', Payer: 'facility_id',
 PrescriptionItem: 'prescription__patient__facility_id',
}

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
    return filter_by_facility(model.objects.all(), user, field=field)

@login_required
def workspace(request):
    links = [{'slug':key,'label':conf[1]} for key,conf in MODULES.items() if allowed(request.user,conf[4])]
    encounters = filter_by_facility(Encounter.objects.filter(status='open'), request.user)
    show_clinical = allowed(request.user,['clinician','nurse'])
    return render(request,'operations/home.html',{
        'unreviewed_results':scoped(OrderResult,request.user,'order__patient__facility_id').filter(approved_at__isnull=True).count(),
        'overdue_referrals':scoped(Referral,request.user,'patient__facility_id').filter(status__in=['open','accepted'],due_date__lt=timezone.localdate()).count(),
        'failed_reminders':scoped(Reminder,request.user,'patient__facility_id').filter(status='failed').count(),
        'expiring_batches':scoped(Batch,request.user,'location__facility_id').filter(quantity_on_hand__gt=0,expiry__lte=timezone.localdate()+timedelta(days=30)).count(),
        'modules':links, 'active_visits':encounters.count(),
        'pending_results':filter_by_patient_facility(Order.objects.filter(status='ordered',order_type='lab'),request.user).count(),
        'open_referrals':filter_by_patient_facility(Referral.objects.filter(status='open'),request.user).count(),
        'admissions_count':filter_by_patient_facility(Admission.objects.filter(discharged_at__isnull=True),request.user).count(),
        'visits':encounters.select_related('patient','clinician').order_by('started_at')[:50] if show_clinical else [],
    })

@login_required
def collection(request, slug):
    model,title,fields,scope,roles = config(request,slug)
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
            elif related in RELATIONS:
                field.queryset = scoped(related,request.user,RELATIONS[related])
            else:
                field.queryset = field.queryset.none()
            if related is User:
                field.queryset = field.queryset.filter(role='clinician',is_active=True)
            if related is Bed:
                field.queryset = field.queryset.filter(active=True).exclude(admission__discharged_at__isnull=True,admission__isnull=False)
            if related is Admission:
                field.queryset = field.queryset.filter(discharged_at__isnull=True)
            if related is Order:
                field.queryset = field.queryset.exclude(status='cancelled')
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                if hasattr(obj,'created_by_id'):
                    obj.created_by = request.user
                if isinstance(obj,Reminder) and (not obj.consent_confirmed or not obj.patient.phone):
                    raise ValidationError('Record consent and a patient phone number before scheduling a reminder.')
                if isinstance(obj,DuplicateReview) and (obj.patient_id==obj.candidate_id or obj.patient.facility_id!=obj.candidate.facility_id):
                    raise ValidationError('Choose two different patient records in the same facility.')
                if isinstance(obj,ClinicalEntry) and obj.supersedes_id and obj.supersedes.patient_id != obj.patient_id:
                    raise ValidationError('Amendments must belong to the same patient.')
                if isinstance(obj,OrderResult):
                    obj.recorded_by=request.user
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
                obj.save()
                if isinstance(obj,ClinicalEntry) and obj.kind == 'allergy':
                    Patient.objects.filter(pk=obj.patient_id).update(allergy_status='recorded')
            messages.success(request,'Record saved.')
            return redirect('suite-collection',slug=slug)
        except (ValidationError,IntegrityError) as exc:
            form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'A conflicting record already exists. Refresh and try again.')
    records = scoped(model,request.user,scope).order_by('-pk')[:100]
    rows=[]
    for obj in records:
        state = getattr(obj,'status','')
        if isinstance(obj,OrderResult): state = 'Released' if obj.approved_at else 'Awaiting review'
        if isinstance(obj,Admission): state = 'Discharged' if obj.discharged_at else 'Admitted'
        values=[]
        for field in fields:
            if field == 'attachment':
                continue
            value=getattr(obj,field)
            if isinstance(value,bool): value='Yes' if value else 'No'
            values.append(str(value or '—')[:180])
        rows.append({'obj':obj,'values':values,'state':state})
    return render(request,'operations/collection.html',{'title':title,'slug':slug,'form':form,'rows':rows,'available_beds':scoped(Bed,request.user,'facility_id').filter(active=True).exclude(admission__discharged_at__isnull=True,admission__isnull=False) if slug=='admissions' else [],'headers':[model._meta.get_field(f).verbose_name for f in fields if f!='attachment']})

@login_required
@require_POST
def action(request,slug,pk,operation):
    model,title,fields,scope,roles=config(request,slug)
    try:
        with transaction.atomic():
            obj=get_object_or_404(scoped(model,request.user,scope).select_for_update(),pk=pk)
            if slug == 'bookings' and operation in ('confirmed','cancelled','no_show'):
                obj.status=operation;obj.save()
            elif slug == 'reminders' and operation == 'cancel':
                if obj.status not in ('pending','failed'): raise ValidationError('Only pending or failed reminders can be cancelled.')
                obj.status='cancelled';obj.save()
            elif slug == 'reminders' and operation == 'retry':
                if obj.status != 'failed': raise ValidationError('Only failed reminders can be retried.')
                obj.status='pending';obj.save()
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
    except ValidationError as exc:
        messages.error(request,'; '.join(exc.messages))
    return redirect('suite-collection',slug=slug)

@login_required
def patient_summary(request,pk):
    if not allowed(request.user,['clinician','nurse','pharmacy','lab']): raise PermissionDenied
    patient=get_object_or_404(filter_by_facility(Patient.objects.all(),request.user),pk=pk)
    return render(request,'operations/patient.html',{'patient':patient,'entries':ClinicalEntry.objects.filter(patient=patient).select_related('created_by').order_by('-created_at'),'referrals':Referral.objects.filter(patient=patient).order_by('-created_at'),'grants':PortalGrant.objects.filter(patient=patient).order_by('-created_at')})

@login_required
def result_download(request,pk):
    if not allowed(request.user,['clinician','nurse','lab']): raise PermissionDenied
    result=get_object_or_404(filter_by_patient_facility(OrderResult.objects.all(),request.user,prefix='order__patient__'),pk=pk)
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
        quantity=forms.DecimalField(max_digits=12,decimal_places=2,min_value=Decimal('0.01'),required=False)
        batch_number=forms.CharField(max_length=64,required=False)
        expiry=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
        reason=forms.CharField(max_length=250)
    form=StockForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        try:
            with transaction.atomic():
                op=data['operation'];batch=data['batch'];location=data['location']
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
