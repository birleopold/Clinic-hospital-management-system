from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.debug import sensitive_post_parameters
from common.facility_scope import filter_by_facility,user_staff_facility_id
from common.service_policy import SERVICES,PRESETS,DEPENDENCIES
from common.mfa import record
from .models import Facility,FacilityConfiguration,User,StaffProfile,Department


def admin_role(user):
    if not user.is_active or not(user.is_superuser or user.role=='admin'):raise PermissionDenied


def role_choices(facility_id):
    conf=FacilityConfiguration.objects.filter(facility_id=facility_id).first() if str(facility_id).isdigit() else None
    active=set(conf.enabled_services) if conf else set(SERVICES)
    needs={'reception':{'patients','appointments'},'clinician':{'clinical','lab','imaging'},'nurse':{'clinical','inpatient','maternity','vaccination'},'lab':{'lab'},'radiology':{'imaging'},'pharmacy':{'pharmacy'},'cashier':{'billing'},'store':{'inventory'},'manager':{'management','billing','inventory'}}
    return [(key,label) for key,label in User.ROLE_CHOICES if key=='admin' or bool(active & needs.get(key,set()))]


@login_required
def configure(request):
    admin_role(request.user)
    facilities=filter_by_facility(Facility.objects.filter(is_active=True),request.user,'pk')
    fid=request.POST.get('facility') or request.GET.get('facility') or user_staff_facility_id(request.user)
    facility=facilities.filter(pk=fid).first() if str(fid).isdigit() else None
    current=FacilityConfiguration.objects.filter(facility=facility).first() if facility else None
    class Form(forms.Form):
        facility=forms.ModelChoiceField(queryset=facilities)
        service_type=forms.ChoiceField(choices=FacilityConfiguration._meta.get_field('service_type').choices)
        display_name=forms.CharField(max_length=160,label='Business / facility display name')
        tagline=forms.CharField(max_length=250,required=False)
        contact_phone=forms.CharField(max_length=40,required=False)
        enabled_services=forms.MultipleChoiceField(choices=[(key,f'{name} — {description}') for key,(name,description) in SERVICES.items()],widget=forms.CheckboxSelectMultiple,label='Services available at this site')
        revision=forms.IntegerField(widget=forms.HiddenInput,initial=0)
    initial={'facility':facility,'service_type':'clinic','enabled_services':PRESETS['clinic'],'display_name':facility.name if facility else ''}
    if current:initial.update({key:getattr(current,key) for key in ['service_type','display_name','tagline','contact_phone','enabled_services','revision']})
    preset=request.GET.get('preset')
    if preset in PRESETS:initial.update(service_type=preset,enabled_services=PRESETS[preset])
    form=Form(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        try:
            selected=set(data['enabled_services'])
            missing={need for key in selected for need in DEPENDENCIES.get(key,[]) if need not in selected}
            if missing:raise ValidationError('Also enable required supporting services: '+', '.join(SERVICES[key][0] for key in sorted(missing)))
            with transaction.atomic():
                target=facilities.select_for_update().get(pk=data['facility'].pk)
                obj=FacilityConfiguration.objects.select_for_update().filter(facility=target).first()
                if (obj.revision if obj else 0)!=data['revision']:raise ValidationError('Configuration changed; reload before saving.')
                if not obj:obj=FacilityConfiguration(facility=target,configured_by=request.user,revision=0)
                for key in ['service_type','display_name','tagline','contact_phone','enabled_services']:setattr(obj,key,data[key])
                obj.revision+=1;obj.configured_by=request.user;obj.full_clean();obj.save()
                record(request.user,'facility_services_changed',f'Facility {target.pk}; revision {obj.revision}; services: '+','.join(sorted(selected)))
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('suite-home')
    return render(request,'accounts/facility_setup.html',{'form':form,'facility':facility,'presets':PRESETS})


@login_required
@sensitive_post_parameters('password')
def staff(request):
    admin_role(request.user)
    facilities=filter_by_facility(Facility.objects.filter(is_active=True),request.user,'pk')
    class Form(forms.Form):
        facility=forms.ModelChoiceField(queryset=facilities)
        username=forms.CharField(max_length=150)
        first_name=forms.CharField(max_length=150)
        last_name=forms.CharField(max_length=150)
        email=forms.EmailField(required=False)
        role=forms.ChoiceField(choices=role_choices(request.POST.get('facility') or user_staff_facility_id(request.user)))
        password=forms.CharField(widget=forms.PasswordInput,help_text='Provide securely to the staff member; never send passwords in ordinary messages.')
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        data=dict(form.cleaned_data)
        try:
            with transaction.atomic():
                facility=facilities.select_for_update().get(pk=data.pop('facility').pk)
                if User.objects.filter(username=data['username']).exists():raise ValidationError('Choose another username.')
                password=data.pop('password');user=User(**data)
                validate_password(password,user);user.full_clean(exclude=['password','last_login','date_joined']);user.set_password(password);user.save()
                StaffProfile.objects.update_or_create(user=user,defaults={'facility':facility})
                record(user,'staff_recruited',f'Facility {facility.pk}; role {user.role}',request.user)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('facility-staff')
    rows=User.objects.filter(staff_profile__facility__in=facilities,is_superuser=False).select_related('staff_profile__facility').order_by('username')
    return render(request,'accounts/staff_setup.html',{'form':form,'staff':Paginator(rows,25).get_page(request.GET.get('page'))})


@login_required
def staff_access(request,pk):
    admin_role(request.user)
    facilities=filter_by_facility(Facility.objects.filter(is_active=True),request.user,'pk')
    target=get_object_or_404(User.objects.filter(staff_profile__facility__in=facilities,is_superuser=False),pk=pk)
    class Form(forms.Form):
        role=forms.ChoiceField(choices=role_choices(target.staff_profile.facility_id))
        is_active=forms.BooleanField(required=False,label='Account enabled')
        reason=forms.CharField(max_length=200)
    form=Form(request.POST or None,initial={'role':target.role,'is_active':target.is_active})
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        try:
            with transaction.atomic():
                # Serialize staffing changes by facility, including last-admin checks.
                facility=facilities.select_for_update().get(pk=target.staff_profile.facility_id)
                target=User.objects.select_for_update().get(pk=pk)
                if target.pk==request.user.pk:raise ValidationError('Another facility administrator must change your own access.')
                if target.role=='admin' and (data['role']!='admin' or not data['is_active']) and not User.objects.filter(staff_profile__facility=facility,role='admin',is_active=True).exclude(pk=pk).exists():raise ValidationError('Keep at least one active facility administrator.')
                target.role=data['role'];target.is_active=data['is_active'];target.save(update_fields=['role','is_active'])
                record(target,'staff_access_changed',data['reason'],request.user)
        except ValidationError as exc:form.add_error(None,'; '.join(exc.messages))
        else:return redirect('facility-staff')
    return render(request,'operations/workflow_form.html',{'title':f'Staff access: {target.username}','form':form,'help':'Role changes apply to subsequent requests. Deactivation prevents login. Resolve outstanding duty/work before offboarding through the workforce checklist.'})


@login_required
def control(request):
    if not request.user.is_superuser:raise PermissionDenied
    sites=Facility.objects.select_related('configuration').order_by('name')
    return render(request,'accounts/owner_control.html',{'sites':Paginator(sites,25).get_page(request.GET.get('page'))})
