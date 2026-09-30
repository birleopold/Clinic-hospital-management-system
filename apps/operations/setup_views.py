import csv
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render,redirect,get_object_or_404
from apps.accounts.models import Facility,Department,StaffProfile
from common.facility_scope import filter_by_facility
from .extension_services import role
from .models import PatientImportBatch, DiagnosticTemplate, ProgrammeDefinition
from . import import_services as service


@login_required
def setup(request):
    role(request.user,('admin','manager'))
    facility_ids=filter_by_facility(Facility.objects.filter(is_active=True),request.user,'pk').values_list('pk',flat=True)
    cards=[('Active facilities',len(facility_ids),'admin:accounts_facility_changelist'),('Active departments',Department.objects.filter(facility_id__in=facility_ids,is_active=True).count(),'admin:accounts_department_changelist'),('Assigned active staff',StaffProfile.objects.filter(facility_id__in=facility_ids,user__is_active=True).count(),'suite-workforce-directory'),('Published diagnostic templates',DiagnosticTemplate.objects.filter(facility_id__in=facility_ids,status='published').count(),'suite-diagnostic-templates'),('Published programme definitions',ProgrammeDefinition.objects.filter(facility_id__in=facility_ids,status='published').count(),None)]
    return render(request,'operations/setup.html',{'cards':cards})


@login_required
def imports(request):
    role(request.user,('admin','manager'))
    if request.GET.get('download')=='template':
        response=HttpResponse(content_type='text/csv');response['Content-Disposition']='attachment; filename="patient-import-template.csv"'
        csv.writer(response).writerow(service.COLUMNS);return response
    class Form(forms.Form):
        facility=forms.ModelChoiceField(queryset=filter_by_facility(Facility.objects.filter(is_active=True),request.user,'pk'))
        source=forms.CharField(max_length=100,label='Stable source system name')
        file=forms.FileField(label='Patient CSV (UTF-8, maximum 1 MiB / 500 rows)')
    form=Form(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        try:
            batch=service.preview(request.user,form.cleaned_data['facility'],form.cleaned_data['source'],form.cleaned_data['file'].read(1024*1024+1))
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-import-detail',pk=batch.pk)
    rows=filter_by_facility(PatientImportBatch.objects.select_related('facility','created_by'),request.user).order_by('-pk')
    return render(request,'operations/imports.html',{'form':form,'page':Paginator(rows,25).get_page(request.GET.get('page'))})


@login_required
def detail(request,pk):
    role(request.user,('admin','manager'))
    batch=get_object_or_404(filter_by_facility(PatientImportBatch.objects.all(),request.user),pk=pk)
    class Form(forms.Form):reason=forms.CharField(max_length=250,label='Independent review and reconciliation evidence')
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:service.commit(pk,request.user,form.cleaned_data['reason'])
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-import-detail',pk=pk)
    page=Paginator(batch.rows,25).get_page(request.GET.get('page'))
    return render(request,'operations/import_detail.html',{'batch':batch,'form':form,'page':page})
