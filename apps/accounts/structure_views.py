"""Scoped department and service-room configuration in the ordinary application."""
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction,IntegrityError
from django.shortcuts import render,redirect,get_object_or_404
from django.core.paginator import Paginator
from common.facility_scope import filter_by_facility
from common.mfa import record
from apps.operations.models import ServiceRoom
from apps.operations.workforce_services import facility_lock
from .models import Facility,Department


@login_required
def structure(request,kind,pk=None):
    if not (request.user.is_superuser or request.user.role in ('admin','manager')):raise PermissionDenied
    if kind not in ('departments','rooms'):raise PermissionDenied
    model=Department if kind=='departments' else ServiceRoom
    qs=filter_by_facility(model.objects.select_related('facility'),request.user)
    obj=get_object_or_404(qs,pk=pk) if pk else None
    fields=['facility','name','code','is_active'] if kind=='departments' else ['facility','name','directions']
    Form=forms.modelform_factory(model,fields=fields)
    form=Form(request.POST or None,instance=obj)
    form.fields['facility'].queryset=filter_by_facility(Facility.objects.filter(is_active=True),request.user,'pk')
    if obj:form.fields['facility'].disabled=True
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                facility_lock(request.user,form.cleaned_data['facility'].pk)
                if obj:
                    model.objects.select_for_update().get(pk=obj.pk)
                candidate=form.save(commit=False)
                candidate.name=candidate.name.strip()
                if model.objects.filter(facility=candidate.facility,name__iexact=candidate.name).exclude(pk=candidate.pk).exists():raise ValidationError('This name is already configured at the facility. Edit that record instead.')
                candidate.full_clean();candidate.save()
                record(request.user,'facility_structure_changed',f'{kind}; record {candidate.pk}; facility {candidate.facility_id}')
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Configuration changed; reload and review the existing record.')
        else:return redirect('facility-structure',kind=kind)
    return render(request,'accounts/structure.html',{'form':form,'kind':kind,'editing':obj,'page':Paginator(qs.order_by('facility__name','name'),25).get_page(request.GET.get('page'))})
