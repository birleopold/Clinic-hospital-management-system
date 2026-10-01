import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import render,redirect,get_object_or_404
from django.core.paginator import Paginator
from django.views.decorators.cache import never_cache
from common.facility_scope import filter_by_facility
from .models import ApprovalGrant,ApprovalPolicy,Facility,User
from . import approval_services as service
from .approval_models import OPERATIONS

class GrantForm(forms.ModelForm):
    request_key=forms.UUIDField(widget=forms.HiddenInput)
    class Meta:
        model=ApprovalGrant
        fields=['facility','operation','approver','maximum','starts_at','ends_at','reason']
        widgets={'starts_at':forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'),'ends_at':forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M')}
        labels={'maximum':'Maximum approved amount · UGX'}

@login_required
@never_cache
def matrix(request):
    service.administrator(request.user)
    facilities=filter_by_facility(Facility.objects.filter(is_active=True),request.user,field='pk')
    form=GrantForm(request.POST if request.method=='POST' and request.POST.get('action')=='grant' else None,initial={'request_key':uuid.uuid4()})
    form.fields['facility'].queryset=facilities
    form.fields['approver'].queryset=User.objects.filter(is_active=True,role__in=['admin','manager'],staff_profile__facility__in=facilities).exclude(pk=request.user.pk)
    if request.method=='POST':
        try:
            action=request.POST.get('action')
            if action=='grant' and form.is_valid():service.grant(request.user,**form.cleaned_data)
            elif action=='policy':
                facility=get_object_or_404(facilities,pk=request.POST.get('facility'))
                service.configure(request.user,facility.pk,request.POST.get('operation'),request.POST.get('enabled')=='1',int(request.POST.get('revision','0')),request.POST.get('reason',''))
            elif action=='revoke':
                obj=get_object_or_404(filter_by_facility(ApprovalGrant.objects.all(),request.user),pk=request.POST.get('grant'))
                service.revoke(request.user,obj.pk,request.POST.get('reason',''))
            else:
                if action!='grant':raise ValidationError('Choose a supported approval matrix action.')
                raise ValidationError('Correct the grant fields below.')
        except (ValidationError,ValueError,IntegrityError) as exc:
            messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Changed or duplicate authority. Reload and review the existing grant.')
        else:return redirect('approval-matrix')
    policies={(p.facility_id,p.operation):p for p in ApprovalPolicy.objects.filter(facility__in=facilities)}
    rows=[{'facility':f,'operation':key,'label':label,'policy':policies.get((f.pk,key))} for f in facilities for key,label in OPERATIONS]
    grants=filter_by_facility(ApprovalGrant.objects.select_related('facility','approver','created_by'),request.user).order_by('-pk')
    return render(request,'accounts/approval_matrix.html',{'form':form,'rows':rows,'page':Paginator(grants,25).get_page(request.GET.get('page'))})
