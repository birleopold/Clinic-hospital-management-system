import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from apps.accounts.models import Facility
from apps.orders.models import OrderResult
from common.facility_scope import filter_by_facility
from .workforce_views import staff_choices, datetime_field
from .workforce_services import facility_lock
from .models import DiagnosticTemplate, DiagnosticWorkItem, DiagnosticWorksheet, Specimen
from . import diagnostic_services as services


def template_scope(actor):
    services.diagnostic_role(actor)
    qs=filter_by_facility(DiagnosticTemplate.objects.all(),actor)
    from common.service_policy import enabled
    if not enabled(actor,'lab'):qs=qs.exclude(order_type='lab')
    if not enabled(actor,'imaging'):qs=qs.exclude(order_type='imaging')
    if not enabled(actor,'clinical'):qs=qs.exclude(order_type='procedure')
    return qs.filter(order_type='imaging') if actor.role=='radiology' and not actor.is_superuser else qs


@login_required
def board(request):
    orders=services.order_scope(request.user).select_related('patient','diagnostic_work__operator').order_by('created_at')
    kind=request.GET.get('kind','')
    if kind in ('lab','imaging','procedure'):orders=orders.filter(order_type=kind)
    status=request.GET.get('status','ordered')
    if status in ('ordered','completed','cancelled'):orders=orders.filter(status=status)
    q=request.GET.get('q','').strip()[:100]
    if q:
        from django.db.models import Q
        orders=orders.filter(Q(code__icontains=q)|Q(description__icontains=q)|Q(patient__first_name__icontains=q)|Q(patient__last_name__icontains=q))
    return render(request,'operations/diagnostic_board.html',{'page':Paginator(orders,30).get_page(request.GET.get('page')),'kind':kind,'status':status,'q':q})


@login_required
def templates(request):
    qs=template_scope(request.user).order_by('name','-version')
    return render(request,'operations/diagnostic_templates.html',{'page':Paginator(qs,25).get_page(request.GET.get('page'))})


@login_required
def template_create(request):
    services.diagnostic_role(request.user)
    class TemplateForm(forms.ModelForm):
        class Meta:
            model=DiagnosticTemplate
            fields=['facility','name','version','order_type','modality']
    class FieldForm(forms.Form):
        label=forms.CharField(max_length=160)
        type=forms.ChoiceField(initial='text',choices=[('text','Text / findings'),('number','Number'),('choice','Choice')])
        required=forms.BooleanField(required=False)
        unit=forms.CharField(max_length=250,required=False)
        reference=forms.CharField(max_length=250,required=False,help_text='Facility-approved range/context; not an automatically calculated normal range.')
        choices=forms.CharField(required=False,widget=forms.Textarea(attrs={'rows':2}),help_text='For a choice field: one option per line.')
    Formset=forms.formset_factory(FieldForm,extra=3,max_num=60,validate_max=True,can_delete=True)
    form=TemplateForm(request.POST or None);fields=Formset(request.POST or None,prefix='fields')
    form.fields['facility'].queryset=filter_by_facility(Facility.objects.filter(is_active=True),request.user,field='pk')
    if request.user.role=='radiology' and not request.user.is_superuser:form.fields['order_type'].choices=[('imaging','Imaging')]
    if request.method=='POST' and form.is_valid() and fields.is_valid():
        try:
            data=[]
            for row in fields.cleaned_data:
                if not row or row.get('DELETE'):continue
                data.append({'key':f'field_{len(data)+1}','label':row['label'],'type':row['type'],'required':row['required'],'unit':row['unit'],'reference':row['reference'],'choices':row['choices'].splitlines() if row['type']=='choice' else []})
            services.validate_fields(data)
            with transaction.atomic():
                facility_lock(request.user,form.cleaned_data['facility'].pk)
                obj=form.save(commit=False);obj.fields=data;obj.created_by=request.user;obj.save()
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'That template version already exists.')
        else:return redirect('suite-diagnostic-templates')
    return render(request,'operations/diagnostic_template_form.html',{'form':form,'fields':fields})


@login_required
def template_review(request,pk):
    obj=get_object_or_404(template_scope(request.user),pk=pk)
    if request.method!='POST':return HttpResponse('Use POST.',status=405)
    try:
        if not (request.user.is_superuser or request.user.role in ('admin','clinician') or (request.user.role=='lab' and obj.order_type=='lab')):raise PermissionDenied
        from .workforce_services import reason_required
        reason=request.POST.get('reason','')[:250];reason_required(reason)
        with transaction.atomic():
            facility_lock(request.user,obj.facility_id);obj=DiagnosticTemplate.objects.select_for_update().get(pk=pk)
            decision=request.POST.get('decision')
            if decision=='publish':
                if obj.created_by_id==request.user.pk:raise ValidationError('Another qualified reviewer must publish this template.')
                if obj.status!='draft':raise ValidationError('Only draft versions may be published.')
                services.validate_fields(obj.fields);obj.status='published'
            elif decision=='retire':obj.status='retired'
            else:raise ValidationError('Choose publish or retire.')
            obj.reviewed_by=request.user;obj.reviewed_at=timezone.now();obj.review_reason=reason;obj._history_user=request.user;obj.save()
    except ValidationError as exc:messages.error(request,'; '.join(exc.messages))
    return redirect('suite-diagnostic-templates')


@login_required
def order_detail(request,pk):
    order=get_object_or_404(services.order_scope(request.user).select_related('patient'),pk=pk)
    work=DiagnosticWorkItem.objects.filter(order=order).first()
    class ScheduleForm(forms.Form):
        operator=forms.ModelChoiceField(queryset=staff_choices(request.user).filter(staff_profile__facility_id=order.patient.facility_id,role__in=['admin','clinician','lab','radiology']))
        modality=forms.CharField(max_length=30,required=False)
        scheduled_at=datetime_field(required=False)
        preparation_note=forms.CharField(max_length=250,required=False)
        revision=forms.IntegerField(widget=forms.HiddenInput())
    form=ScheduleForm(request.POST or None,initial={'operator':work.operator_id if work else None,'modality':work.modality if work else '', 'scheduled_at':work.scheduled_at if work else None,'preparation_note':work.preparation_note if work else '', 'revision':work.revision if work else 1})
    if request.method=='POST':
        try:
            if request.POST.get('action')=='start':services.start(pk,request.user);return redirect('suite-diagnostic-order',pk=pk)
            elif form.is_valid():services.schedule(pk,request.user,**form.cleaned_data);return redirect('suite-diagnostic-order',pk=pk)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
    templates=template_scope(request.user).filter(facility_id=order.patient.facility_id,order_type=order.order_type,status='published')
    sheets=DiagnosticWorksheet.objects.filter(result__order=order).select_related('result','created_by').order_by('-pk')
    return render(request,'operations/diagnostic_order.html',{'order':order,'patient':order.patient,'work':work,'form':form,'templates':templates,'sheets':sheets})


@login_required
def worksheet(request,pk,template_id):
    order=get_object_or_404(services.order_scope(request.user).select_related('patient'),pk=pk)
    template=get_object_or_404(template_scope(request.user),pk=template_id,facility_id=order.patient.facility_id,order_type=order.order_type,status='published')
    class Form(forms.Form):
        request_key=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput())
        specimen=forms.ModelChoiceField(queryset=Specimen.objects.filter(order=order,status='received'),required=order.order_type=='lab')
        critical=forms.BooleanField(required=False,label='Critical result requiring clinical acknowledgment')
        supersedes=forms.ModelChoiceField(queryset=OrderResult.objects.filter(order=order,approved_at__isnull=False),required=False,label='Amends released result (if applicable)')
    form=Form(request.POST or None)
    for field in template.fields:
        kwargs={'label':field['label'],'required':field.get('required',False),'help_text':' · '.join(v for v in [field.get('unit',''),field.get('reference','')] if v)}
        if field.get('type')=='choice':item=forms.ChoiceField(choices=[('','Select')]+[(v,v) for v in field['choices']],**kwargs)
        else:item=forms.CharField(max_length=5000,widget=forms.Textarea(attrs={'rows':2}) if field.get('type')=='text' else forms.TextInput(attrs={'inputmode':'decimal'}),**kwargs)
        form.fields[field['key']]=item
    if request.method=='POST' and form.is_valid():
        try:
            sheet=services.submit(pk,request.user,template,{f['key']:form.cleaned_data[f['key']] for f in template.fields},form.cleaned_data['request_key'],form.cleaned_data['supersedes'],form.cleaned_data['specimen'],form.cleaned_data['critical'])
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'A competing report changed this order. Reload before retrying.')
        else:return redirect('suite-diagnostic-sheet',pk=sheet.pk)
    return render(request,'operations/workflow_form.html',{'form':form,'patient':order.patient,'title':str(template),'help':'Record observed findings. This draft requires independent review before it becomes a patient report.'})


@login_required
def sheet_detail(request,pk):
    sheet=get_object_or_404(DiagnosticWorksheet.objects.select_related('result__order__patient','result__approved_by','created_by'),pk=pk,result__order__in=services.order_scope(request.user))
    class Form(forms.Form):
        decision=forms.ChoiceField(choices=[('release','Release after review'),('withdraw','Withdraw draft')])
        reason=forms.CharField(max_length=250)
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:services.review(pk,request.user,**form.cleaned_data)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-diagnostic-sheet',pk=pk)
    rows=[(field['label'],sheet.answers.get(field['key'],''),field.get('unit',''),field.get('reference','')) for field in sheet.snapshot['fields']]
    return render(request,'operations/diagnostic_sheet.html',{'sheet':sheet,'patient':sheet.result.order.patient,'rows':rows,'form':form})


@login_required
def report(request,pk):
    order=get_object_or_404(services.order_scope(request.user).select_related('patient__facility'),pk=pk)
    released=order.results.filter(approved_at__isnull=False).select_related('approved_by','recorded_by').order_by('recorded_at')
    superseded=released.filter(supersedes__isnull=False).values_list('supersedes_id',flat=True)
    results=list(released.exclude(pk__in=superseded))
    if not results:return HttpResponse('No released results available.',status=404)
    if request.GET.get('download')=='text':
        patient=order.patient
        content=f'{patient.facility}\nPatient: {patient}\nMRN: {patient.medical_record_id}\nOrder #{order.pk}: {order.description or order.code}\n\n'
        for result in results:content+=f'Result #{result.pk}'+(' — CRITICAL' if result.critical else '')+f'\n{result.analyte}: {result.value} {result.units}\nReference: {result.reference_range}\n{result.result_text}\nReleased by {result.approved_by} at {result.approved_at.isoformat()}\n\n'
        response=HttpResponse(content,content_type='text/plain; charset=utf-8');response['Content-Disposition']=f'attachment; filename="report-{order.pk}.txt"';return response
    return render(request,'operations/diagnostic_report.html',{'order':order,'results':results})
