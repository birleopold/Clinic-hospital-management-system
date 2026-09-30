from common.facility_scope import filter_by_facility

def workspace_context(request):
    user=request.user
    if not user.is_authenticated:return {}
    from common.mfa import required
    if required(user) and not getattr(user,'otp_device',None):return {}
    from apps.accounts.models import Facility
    result={'selected_facility':Facility.objects.filter(pk=getattr(user,'_active_facility_id',None)).first()}
    from common.service_policy import navigation, profile, enabled, SERVICES
    conf=profile(user)
    result.update(workspace_navigation=navigation(user),facility_brand=conf,services={key:enabled(user,key) for key in SERVICES},show_global_search=enabled(user,'patients') and (user.is_superuser or user.role in ('admin','clinician','nurse','pharmacy','lab','reception','cashier','manager')))
    # Query-selected identity is re-scoped. It never grants view or write permission.
    pk=request.GET.get('patient','')
    if pk.isdigit() and (user.is_superuser or user.role in ('admin','reception','nurse','clinician','pharmacy','lab','cashier','manager')):
        from apps.demographics.models import Patient
        result['context_patient']=filter_by_facility(Patient.objects.filter(merged_into__isnull=True),user).filter(pk=int(pk)).first()
    if not result.get('context_patient') and (user.is_superuser or user.role in ('admin','clinician','nurse','lab')):
        for key,model_path in [('order','orders.Order'),('admission','operations.Admission')]:
            value=request.GET.get(key,'')
            if value.isdigit():
                from django.apps import apps
                model=apps.get_model(model_path)
                parent=filter_by_facility(model.objects.select_related('patient'),user,field='patient__facility_id').filter(pk=int(value)).first()
                if parent:result['context_patient']=parent.patient
    match=request.resolver_match
    if match:
        label=match.kwargs.get('slug') or match.url_name or ''
        result['page_breadcrumb']=label.replace('suite-','').replace('-',' ').title()
    return result
