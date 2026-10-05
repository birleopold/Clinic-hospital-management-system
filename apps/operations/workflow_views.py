from datetime import timedelta
from pathlib import Path
import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import Q, CharField, TextField
from django.http import JsonResponse, Http404, FileResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from common.facility_scope import filter_by_facility
from apps.accounts.models import User
from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from .models import WorkTask, NoteTemplate, ConsultationNote, PatientDocument, Bed, Admission, TheatreCase, Specimen
from apps.orders.models import OrderResult
from .views import allowed, config, collection_form

ROLES=('reception','nurse','clinician','lab','radiology','pharmacy','cashier','store','manager')

def require(user, roles):
    if not allowed(user,roles):raise PermissionDenied

def patient_for(request, pk):
    if not str(pk).isdigit():raise Http404
    patient=get_object_or_404(filter_by_facility(Patient.objects.all(),request.user),pk=pk)
    if patient.merged_into_id:raise Http404('Open the canonical patient chart.')
    return patient

def task_scope(user):
    qs=filter_by_facility(WorkTask.objects.all(),user,field='facility_id')
    if user.is_superuser or user.role=='admin':return qs
    return qs.filter(Q(audience=user.role)|Q(created_by=user))

@login_required
@never_cache
def tasks(request):
    require(request.user,ROLES)
    qs=task_scope(request.user).select_related('patient','owner','created_by')
    status=request.GET.get('status','open')
    if status in ('open','in_progress','completed','cancelled'):qs=qs.filter(status=status)
    elif status!='all':raise Http404
    mine=request.GET.get('mine')=='1'
    if mine:qs=qs.filter(owner=request.user)
    return render(request,'operations/tasks.html',{'page':Paginator(qs.order_by('due_at','pk'),25).get_page(request.GET.get('page')),'status':status,'mine':mine})

@login_required
@never_cache
def task_create(request, pk=None):
    require(request.user,ROLES)
    patient=patient_for(request,pk) if pk else None
    from common.facility_scope import user_staff_facility_id
    facility_id=patient.facility_id if patient else user_staff_facility_id(request.user)
    if not facility_id:raise PermissionDenied('Assign a facility before creating a general task.')
    source_kind=request.GET.get('source','')
    source=None
    if source_kind:
        if not request.GET.get('record','').isdigit():raise Http404
        source_model,_,_,source_scope,_=config(request,source_kind)
        if source_kind not in ('results','referrals','reminders'):raise Http404
        from .views import scoped
        source=get_object_or_404(scoped(source_model,request.user,source_scope),pk=request.GET.get('record'))
        source_patient=source.order.patient if source_kind=='results' else source.patient
        if not patient or source_patient.pk!=patient.pk:raise PermissionDenied
    class TaskForm(forms.ModelForm):
        audience=forms.ChoiceField(choices=[(r,r.title()) for r in ROLES])
        class Meta:
            model=WorkTask
            fields=['audience','owner','title','instruction','due_at','encounter']
            widgets={'due_at':forms.DateTimeInput(attrs={'type':'datetime-local'})}
    form=TaskForm(request.POST or None)
    form.fields['owner'].queryset=User.objects.filter(is_active=True,staff_profile__facility_id=facility_id,role__in=ROLES)
    form.fields['encounter'].queryset=Encounter.objects.filter(patient=patient) if patient else Encounter.objects.none()
    if request.method=='POST' and form.is_valid():
        owner=form.cleaned_data['owner']
        if owner and owner.role!=form.cleaned_data['audience']:form.add_error('owner','Owner must belong to the selected department.')
        else:
            with transaction.atomic():
                locked=Patient.objects.select_for_update().get(pk=patient.pk) if patient else None
                if locked and locked.merged_into_id:raise Http404('Patient merged; reload the canonical record.')
                task=form.save(commit=False);task.patient=locked;task.facility_id=facility_id;task.created_by=request.user
                if source:task.source_kind=source_kind;task.source_pk=source.pk
                task.save()
            return redirect('suite-task-detail',pk=task.pk)
    return render(request,'operations/workflow_form.html',{'form':form,'patient':patient,'title':'Create a handoff task','help':'Use a clear next action. Share only information needed by the receiving department.'})

@login_required
@never_cache
def task_detail(request,pk):
    task=get_object_or_404(task_scope(request.user),pk=pk)
    require(request.user,ROLES)
    staff=User.objects.filter(is_active=True,role=task.audience,staff_profile__facility_id=task.facility_id)
    class UpdateForm(forms.Form):
        revision=forms.IntegerField(widget=forms.HiddenInput)
        owner=forms.ModelChoiceField(queryset=staff,required=False)
        status=forms.ChoiceField(choices=WorkTask._meta.get_field('status').choices)
        resolution=forms.CharField(widget=forms.Textarea,required=False)
    form=UpdateForm(request.POST or None,initial={'revision':task.revision,'owner':task.owner_id,'status':task.status,'resolution':task.resolution})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            task=get_object_or_404(task_scope(request.user).select_for_update(),pk=pk)
            if form.cleaned_data['revision']!=task.revision:form.add_error(None,'Task changed. Reload before updating.')
            elif task.status in ('completed','cancelled'):form.add_error(None,'Resolved tasks are retained unchanged. Create a new task for follow-up.')
            elif form.cleaned_data['status'] in ('completed','cancelled') and not form.cleaned_data['resolution'].strip():form.add_error('resolution','Record the outcome or cancellation reason.')
            else:
                task.owner=form.cleaned_data['owner'];task.status=form.cleaned_data['status'];task.resolution=form.cleaned_data['resolution'];task.revision+=1
                if task.status in ('completed','cancelled'):task.resolved_at=timezone.now()
                task._history_user=request.user;task.save()
                return redirect('suite-task-detail',pk=pk)
    return render(request,'operations/task_detail.html',{'task':task,'patient':task.patient,'form':form,'history':task.history.select_related('history_user').order_by('-history_date')[:50]})

@login_required
@never_cache
def note(request,pk):
    require(request.user,['clinician','nurse'])
    visit=get_object_or_404(filter_by_facility(Encounter.objects.select_related('patient'),request.user),pk=pk)
    patient=visit.patient
    class NoteForm(forms.ModelForm):
        reviewed=forms.BooleanField(label='I reviewed this note and any reused text before signing')
        class Meta:
            model=ConsultationNote
            fields=['template','copied_from','amends','body']
    form=NoteForm(request.POST or None)
    form.fields['template'].queryset=NoteTemplate.objects.filter(facility_id=patient.facility_id).order_by('name','-version')
    for name in ('copied_from','amends'):form.fields[name].queryset=ConsultationNote.objects.filter(patient=patient)
    if request.method=='GET':
        if request.GET.get('template'):
            if not request.GET['template'].isdigit():raise Http404
            template=get_object_or_404(form.fields['template'].queryset,pk=request.GET['template'])
            form.initial.update(template=template.pk,body=template.body)
        if request.GET.get('copy'):
            if not request.GET['copy'].isdigit():raise Http404
            source=get_object_or_404(form.fields['copied_from'].queryset,pk=request.GET['copy'])
            form.initial.update(copied_from=source.pk,body=source.body)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            locked=Patient.objects.select_for_update().get(pk=patient.pk)
            current=Encounter.objects.select_for_update().get(pk=visit.pk)
            if locked.merged_into_id or current.patient_id!=locked.pk:form.add_error(None,'Patient identity changed. Reload the chart.')
            elif current.status!='open':form.add_error(None,'This visit is closed. Open an appropriate new visit to document follow-up.')
            else:
                obj=form.save(commit=False);obj.patient=locked;obj.encounter=current;obj.created_by=request.user
                obj.template_snapshot=obj.template.body if obj.template_id else '';obj.save()
                return redirect(reverse('suite-patient',args=[patient.pk])+'?section=consultations')
    return render(request,'operations/workflow_form.html',{'form':form,'patient':patient,'title':'Sign consultation note','templates':form.fields['template'].queryset,'visit':visit,'prior_notes':ConsultationNote.objects.filter(patient=patient).order_by('-created_at')[:20],'help':'Templates and copied notes are starting points. Signing creates an attributed record; it does not overwrite the original.'})

@login_required
@never_cache
def templates(request):
    require(request.user,['clinician'])
    from apps.accounts.models import Facility
    class TemplateForm(forms.ModelForm):
        class Meta:
            model=NoteTemplate
            fields=['facility','name','version','body']
    form=TemplateForm(request.POST or None)
    form.fields['facility'].queryset=filter_by_facility(Facility.objects.all(),request.user,field='pk')
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False);obj.created_by=request.user
        try:
            with transaction.atomic():obj.save()
            messages.success(request,'Template version published. Existing versions are preserved.');return redirect('suite-note-templates')
        except IntegrityError:form.add_error(None,'This version already exists. Publish a new version.')
    return render(request,'operations/workflow_form.html',{'form':form,'title':'Publish a note template version','help':'Published versions cannot be edited here. Publish a new version to change wording; do not insert unverified patient facts.'})

@login_required
@never_cache
def document(request,pk):
    require(request.user,['clinician','nurse'])
    patient=patient_for(request,pk)
    class DocumentForm(forms.ModelForm):
        class Meta:
            model=PatientDocument
            fields=['title','file','encounter']
        def clean_file(self):
            file=self.cleaned_data['file'];head=file.read(16);file.seek(0)
            if file.size>10*1024*1024:raise forms.ValidationError('Maximum file size is 10 MB.')
            ext=Path(file.name).suffix.lower()
            valid=(ext=='.pdf' and head.startswith(b'%PDF-')) or (ext in ('.jpg','.jpeg') and head.startswith(b'\xff\xd8\xff')) or (ext=='.png' and head.startswith(b'\x89PNG\r\n\x1a\n'))
            if not valid:raise forms.ValidationError('Upload a PDF, JPEG or PNG with matching file content.')
            file.name=f'{uuid.uuid4()}{ext}'
            return file
    form=DocumentForm(request.POST or None,request.FILES or None)
    form.fields['encounter'].queryset=Encounter.objects.filter(patient=patient)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            locked=Patient.objects.select_for_update().get(pk=patient.pk)
            if locked.merged_into_id:form.add_error(None,'Patient identity changed; reload the chart.')
            else:
                obj=form.save(commit=False);obj.patient=locked;obj.created_by=request.user;obj.save()
                return redirect(reverse('suite-patient',args=[patient.pk])+'?section=documents')
    return render(request,'operations/workflow_form.html',{'form':form,'patient':patient,'title':'Attach patient document','help':'PDF, PNG or JPEG, up to 10 MB. Files are downloaded privately, not published or rendered inline.'})

@login_required
@never_cache
def document_download(request,pk):
    require(request.user,['clinician','nurse'])
    obj=get_object_or_404(filter_by_facility(PatientDocument.objects.all(),request.user,field='patient__facility_id'),pk=pk)
    result=FileResponse(obj.file.open('rb'),as_attachment=True,filename=Path(obj.file.name).name)
    result['X-Content-Type-Options']='nosniff';result['Content-Security-Policy']="default-src 'none'"
    return result

@login_required
@never_cache
def lookup(request,slug,field):
    model,title,names,scope,roles=config(request,slug)
    form=collection_form(request,model,names)
    if field not in form.fields or not isinstance(form.fields[field],forms.ModelChoiceField):raise Http404
    selected=form.fields[field];qs=selected.queryset
    query=request.GET.get('q','').strip()[:100]
    if query:
        condition=Q()
        for f in qs.model._meta.fields:
            if isinstance(f,(CharField,TextField)):condition |= Q(**{f'{f.name}__icontains':query})
        if query.isdigit():condition |= Q(pk=int(query))
        if qs.model is Patient:
            try:condition |= Q(medical_record_id=uuid.UUID(query))
            except ValueError:pass
        if condition:qs=qs.filter(condition)
        else:qs=qs.none()
    result=JsonResponse({'results':[{'id':o.pk,'label':selected.label_from_instance(o)} for o in qs.order_by('-pk')[:30]]})
    return result

@login_required
@never_cache
def department_board(request):
    require(request.user,ROLES)
    from apps.appointments.models import QueueTicket
    from apps.orders.models import Order
    from apps.pharmacy.models import Prescription
    from apps.billing.models import Invoice
    from django.db.models import F, Exists, OuterRef
    role=request.user.role
    board=request.GET.get('board',{'admin':'reception','manager':'cashier','store':'pharmacy'}.get(role,role))
    allowed_boards={'reception':['reception'],'nurse':['nurse','ward'],'clinician':['clinician','theatre','ward'],'lab':['lab'],'pharmacy':['pharmacy'],'cashier':['cashier'],'manager':['cashier'],'store':['pharmacy']}.get(role,[])
    if request.user.is_superuser or role=='admin':allowed_boards=['reception','nurse','clinician','lab','pharmacy','cashier','ward','theatre']
    from common.service_policy import enabled
    board_services={'reception':'appointments','nurse':'clinical','clinician':'clinical','lab':'lab','pharmacy':'pharmacy','cashier':'billing','ward':'inpatient','theatre':'theatre'}
    allowed_boards=[b for b in allowed_boards if enabled(request.user,board_services[b])]
    if 'board' not in request.GET and allowed_boards and board not in allowed_boards:board=allowed_boards[0]
    if board not in allowed_boards:raise PermissionDenied
    status=request.GET.get('status','active');rows=[];beds=[];statuses=[('active','Active'),('all','All')]
    patient_id=request.GET.get('patient','')
    selected_patient=None
    if patient_id:selected_patient=patient_for(request,patient_id)
    def scoped(qs,path='patient__facility_id'):
        qs=filter_by_facility(qs,request.user,field=path)
        if selected_patient:qs=qs.filter(**{path.rsplit('facility_id',1)[0]+'pk':selected_patient.pk})
        return qs
    if board in ('reception','nurse','clinician'):
        service={'reception':'triage','nurse':'triage','clinician':'consult'}[board]
        qs=scoped(QueueTicket.objects.filter(service=service)).select_related('patient','assigned_to')
        if status=='active':qs=qs.filter(status__in=['waiting','in_service'])
        qs=qs.order_by('created_at')
        kind='queue'
    elif board=='lab':
        statuses=[('active','Outstanding'),('collection','Awaiting specimen'),('processing','Received / processing'),('review','Awaiting review'),('critical','Critical acknowledgment'),('all','All')]
        qs=scoped(Order.objects.filter(order_type='lab')).select_related('patient','encounter')
        qs=qs.annotate(received=Exists(Specimen.objects.filter(order_id=OuterRef('pk'),status='received')),has_specimen=Exists(Specimen.objects.filter(order_id=OuterRef('pk')).exclude(status='rejected')),draft=Exists(OrderResult.objects.filter(order_id=OuterRef('pk'),approved_at__isnull=True)),critical=Exists(OrderResult.objects.filter(order_id=OuterRef('pk'),approved_at__isnull=False,critical=True,acknowledged_at__isnull=True)))
        if status=='active':qs=qs.filter(Q(status='ordered')|Q(critical=True))
        elif status=='collection':qs=qs.filter(status='ordered',has_specimen=False)
        elif status=='processing':qs=qs.filter(status='ordered',received=True,draft=False)
        elif status=='review':qs=qs.filter(draft=True).exclude(status='cancelled')
        elif status=='critical':qs=qs.filter(critical=True)
        scan=request.GET.get('scan','').strip()
        if scan:
            try:accession=uuid.UUID(scan)
            except ValueError:qs=qs.none()
            else:qs=qs.filter(specimens__accession=accession)
        qs=qs.order_by('created_at');kind='lab'
    elif board=='pharmacy':
        # Store staff get stock controls without access to prescription records.
        if role=='store' and not request.user.is_superuser:return redirect('suite-stock')
        qs=scoped(Prescription.objects.all()).select_related('patient','clinician')
        if status=='active':qs=qs.filter(items__quantity__gt=F('items__dispensed_quantity')).distinct()
        qs=qs.order_by('created_at');kind='pharmacy'
    elif board=='cashier':
        qs=scoped(Invoice.objects.all()).select_related('patient')
        if status=='active':qs=qs.filter(status='ready_to_pay')
        qs=qs.order_by('created_at');kind='cashier'
    elif board=='ward':
        qs=scoped(Admission.objects.all()).select_related('patient','bed')
        if status=='active':qs=qs.filter(discharged_at__isnull=True)
        qs=qs.order_by('bed__ward','bed__name');kind='ward'
        beds=filter_by_facility(Bed.objects.filter(active=True),request.user).annotate(occupied=Exists(Admission.objects.filter(bed_id=OuterRef('pk'),discharged_at__isnull=True))).order_by('ward','name')[:200]
    else:
        qs=scoped(TheatreCase.objects.all()).select_related('patient','room','surgeon')
        if status=='active':qs=qs.exclude(status__in=['completed','cancelled'])
        qs=qs.order_by('starts_at');kind='theatre'
    if status not in dict(statuses):raise Http404
    page=Paginator(qs,25).get_page(request.GET.get('page'))
    return render(request,'operations/department_board.html',{'page':page,'board':board,'kind':kind,'board_options':allowed_boards,'statuses':statuses,'status':status,'scan':request.GET.get('scan',''),'patient':selected_patient,'beds':beds})

@login_required
@never_cache
def handoff(request,pk):
    require(request.user,['reception','nurse','clinician','lab','pharmacy','cashier'])
    from apps.appointments.models import QueueTicket
    patient=patient_for(request,pk)
    from common.service_policy import enabled
    mapping={'triage':'clinical','consult':'clinical','lab':'lab','pharmacy':'pharmacy','cashier':'billing'}
    class HandoffForm(forms.Form):
        service=forms.ChoiceField(choices=[(key,label) for key,label in QueueTicket.SERVICE_CHOICES if enabled(request.user,mapping[key])])
    form=HandoffForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            locked=Patient.objects.select_for_update().get(pk=patient.pk)
            if locked.merged_into_id:form.add_error(None,'Patient identity changed; reload.')
            else:
                service=form.cleaned_data['service']
                existing=QueueTicket.objects.filter(patient=locked,service=service,status__in=['waiting','in_service']).first()
                if not existing:QueueTicket.objects.create(patient=locked,service=service)
                messages.success(request,'Patient is in the selected service queue. Existing active tickets are reused.')
                return redirect('suite-patient',pk=pk)
    return render(request,'operations/workflow_form.html',{'form':form,'patient':patient,'title':'Send patient to a service','help':'This creates a queue handoff. It does not mark clinical work, payment or stock dispensing complete.'})

@login_required
def claim_visit(request,pk):
    if request.method!='POST':return JsonResponse({'detail':'Use POST.'},status=405)
    require(request.user,['clinician'])
    if request.user.role!='clinician':raise PermissionDenied('A clinician account must accept the visit.')
    with transaction.atomic():
        visit=get_object_or_404(filter_by_facility(Encounter.objects.select_for_update(),request.user),pk=pk)
        if visit.status!='open':return JsonResponse({'detail':'This visit is closed.'},status=409)
        if visit.clinician_id and visit.clinician.role=='clinician' and visit.clinician_id!=request.user.pk:
            return JsonResponse({'detail':'Another clinician owns this visit. Arrange an explicit reassignment through the facility administrator.'},status=409)
        visit.clinician=request.user;visit._history_user=request.user;visit.save(update_fields=['clinician'])
    return redirect('ehr-encounter-detail',encounter_id=visit.pk)
