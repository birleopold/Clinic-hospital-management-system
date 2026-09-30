from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.utils import timezone
from apps.accounts.models import Facility
from common.facility_scope import filter_by_facility
from .models import ManagementCase, CorrectiveAction, FacilityAsset, AssetEvent, StaffChecklist, OperatingBudget, OperatingExpense
from .workforce_views import staff_choices, is_manager
from .workforce_services import manager
from . import management_services as services

REGISTERS={
 'cases':(ManagementCase,'Incidents and complaints','facility_id',['facility','kind','severity','title','details','owner','due_at']),
 'actions':(CorrectiveAction,'Corrective actions','case__facility_id',['case','owner','description','due_at']),
 'assets':(FacilityAsset,'Equipment and assets','facility_id',['facility','tag','name','serial_number','location','custodian','maintenance_due','calibration_due']),
 'asset-events':(AssetEvent,'Equipment service records','asset__facility_id',['asset','kind','vendor','cost','evidence','next_due']),
 'checklists':(StaffChecklist,'Staff checklists','facility_id',['facility','staff','owner','kind','title','version','instructions','due_at']),
 'budgets':(OperatingBudget,'Operating budgets · UGX','facility_id',['facility','cost_centre','starts_on','ends_on','amount']),
 'expenses':(OperatingExpense,'Budgeted expenses · UGX','budget__facility_id',['budget','incurred_on','payee','reference','description','amount']),
}


def scoped(kind,user):
    if kind not in REGISTERS:raise PermissionDenied
    model,title,field,fields=REGISTERS[kind]
    qs=filter_by_facility(model.objects.all(),user,field=field)
    if kind=='checklists' and not is_manager(user):qs=qs.filter(Q(staff=user)|Q(owner=user))
    else:manager(user)
    return qs


@login_required
def home(request):
    manager(request.user);now=timezone.now();today=timezone.localdate()
    cards=[('Open incidents and complaints',scoped('cases',request.user).exclude(status='closed').count(),'cases'),('Overdue corrective actions',scoped('actions',request.user).filter(completed_at__isnull=True,due_at__lt=now).count(),'actions'),('Equipment unavailable',scoped('assets',request.user).filter(status='out_of_service').count(),'assets'),('Maintenance/calibration due',scoped('assets',request.user).exclude(status='retired').filter(Q(maintenance_due__lte=today)|Q(calibration_due__lte=today)).count(),'assets'),('Staff checklist review due',scoped('checklists',request.user).filter(reviewed_at__isnull=True,due_at__lt=now).count(),'checklists'),('Expense approvals',scoped('expenses',request.user).filter(status='requested').count(),'expenses')]
    return render(request,'operations/management_home.html',{'cards':cards,'now':now})


@login_required
def register(request,kind):
    qs=scoped(kind,request.user)
    model,title,field,fields=REGISTERS[kind]
    page=Paginator(qs.order_by('-pk'),25).get_page(request.GET.get('page'))
    if kind=='budgets':
        for obj in page:obj.approved_expenses=obj.expenses.filter(status='approved').aggregate(total=Sum('amount'))['total'] or 0;obj.remaining=obj.amount-obj.approved_expenses
    return render(request,'operations/management_register.html',{'kind':kind,'title':title,'page':page,'manager':is_manager(request.user)})


@login_required
def create(request,kind):
    manager(request.user)
    if kind not in REGISTERS:raise PermissionDenied
    model,title,field,fields=REGISTERS[kind]
    Form=forms.modelform_factory(model,fields=fields)
    form=Form(request.POST or None)
    for name,field_obj in form.fields.items():
        if name=='facility':field_obj.queryset=filter_by_facility(Facility.objects.filter(is_active=True),request.user,field='pk')
        elif name in ('owner','staff','custodian'):field_obj.queryset=staff_choices(request.user)
        elif name=='case':field_obj.queryset=scoped('cases',request.user).filter(status='open')
        elif name=='asset':field_obj.queryset=scoped('assets',request.user).exclude(status='retired')
        elif name=='budget':field_obj.queryset=scoped('budgets',request.user).filter(status='approved')
        elif isinstance(field_obj,forms.DateTimeField):field_obj.widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M')
        elif isinstance(field_obj,forms.DateField):field_obj.widget=forms.DateInput(attrs={'type':'date'})
        if name in ('owner',) and kind in ('cases','actions'):field_obj.queryset=field_obj.queryset.filter(Q(role__in=['admin','manager'])|Q(is_superuser=True))
    if request.method=='POST' and form.is_valid():
        try:services.create_record(request.user,form)
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Duplicate or changed record; check the register before retrying.')
        else:messages.success(request,'Management record created.');return redirect('suite-management-register',kind=kind)
    return render(request,'operations/workflow_form.html',{'form':form,'title':'New · '+title,'help':'Records retain their history. Expense approval records a budget obligation, not a cash payment. Use supporting document references.'})


@login_required
def action(request,kind,pk):
    if request.method!='POST':return HttpResponse('Use POST.',status=405)
    obj=get_object_or_404(scoped(kind,request.user),pk=pk)
    try:
        revision=request.POST.get('revision')
        if revision is not None:
            try:revision=int(revision)
            except ValueError:raise ValidationError('Reload the current record.')
        services.decide(type(obj),pk,request.user,request.POST.get('decision',''),request.POST.get('reason','')[:250],revision)
    except ValidationError as exc:messages.error(request,'; '.join(exc.messages))
    else:messages.success(request,'Action recorded.')
    return redirect('suite-management-register',kind=kind)
