import uuid
from datetime import timedelta
from django import forms
from django.conf import settings
from django.core import signing
from django.core.paginator import Paginator
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction,IntegrityError
from django.http import HttpResponse,HttpResponseForbidden
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.debug import sensitive_post_parameters
from .models import TenantDeployment,OwnerSupportReceipt,User
from . import tenant_services as service
from common.mfa import record
from common.service_policy import SERVICES,PRESETS

@login_required
@never_cache
def console(request):
    service.owner(request.user)
    class Form(forms.Form):
        name=forms.CharField(max_length=160)
        origin=forms.URLField(label='Tenant HTTPS origin',assume_scheme='https')
        bind_port=forms.IntegerField(min_value=1024,max_value=65535,label='Private application port')
        admin_username=forms.CharField(max_length=150)
        service_type=forms.ChoiceField(choices=[(k,k.title()) for k in PRESETS])
        services=forms.MultipleChoiceField(choices=[(key,value[0]) for key,value in SERVICES.items()],widget=forms.CheckboxSelectMultiple)
    form=Form(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:service.create(request.user,**form.cleaned_data)
        except (ValidationError,IntegrityError) as exc:form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'This tenant origin or private port is already registered.')
        else:return redirect('tenant-console')
    return render(request,'accounts/tenants.html',{'form':form,'tenants':Paginator(TenantDeployment.objects.defer('secret_envelope').order_by('name','pk'),25).get_page(request.GET.get('page'))})

@login_required
@never_cache
@require_POST
def action(request,pk):
    service.owner(request.user);obj=get_object_or_404(TenantDeployment,pk=pk)
    action=request.POST.get('action')
    try:
        if action=='bundle':
            response=HttpResponse(service.bundle(request.user,obj),content_type='application/zip');response['Content-Disposition']='attachment; filename="tenant-'+str(obj.key)+'.zip"';return response
        if action=='support':
            token=service.support_ticket(request.user,obj,request.POST.get('reason',''))
            response=render(request,'accounts/support_launch.html',{'origin':obj.origin,'ticket':token,'tenant':obj})
            response['Referrer-Policy']='no-referrer';return response
        service.state(request.user,pk,action,int(request.POST.get('revision','0')),request.POST.get('reason',''))
    except (ValidationError,ValueError) as exc:
        from django.contrib import messages
        messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Reload the current tenant revision.')
    return redirect('tenant-console')

@never_cache
def policy(request):
    if not getattr(settings,'OWNER_CONTROL_PLANE',False) or getattr(settings,'TENANT_KEY',''):raise PermissionDenied
    token=request.GET.get('ticket','')
    # Unverified payload is used only to choose a key; never to authorize policy.
    try:
        from django.core.signing import b64_decode
        import json
        raw=token.split(':',1)[0]
        if len(raw)>2000:raise ValueError
        compressed=raw.startswith('.')
        blob=b64_decode(raw.lstrip('.').encode())
        if compressed:raise ValueError('Compressed policy requests are not supported.')
        key=json.loads(blob)['tenant']
        obj=TenantDeployment.objects.get(key=key)
        secret=service.secrets_for(obj)['support']
        data=signing.loads(token,key=secret,salt='tenant-policy-request',max_age=15,fallback_keys=[])
        if data['tenant']!=str(obj.key):raise ValueError
    except Exception:return HttpResponseForbidden('Invalid tenant policy request.')
    with transaction.atomic():
        obj=TenantDeployment.objects.select_for_update().get(pk=obj.pk)
        obj.last_seen_at=timezone.now()
        if obj.state=='provisioning':obj.state='active';obj.revision+=1
        obj.save(update_fields=['last_seen_at','state','revision'])
    return HttpResponse(signing.dumps({'tenant':str(obj.key),'active':obj.state=='active'},key=secret,salt='tenant-policy-response'),content_type='text/plain')

@csrf_exempt
@never_cache
@require_POST
@sensitive_post_parameters('ticket')
def accept(request):
    key=getattr(settings,'TENANT_KEY','');secret=getattr(settings,'TENANT_SUPPORT_SECRET','')
    if not key or not secret:return HttpResponseForbidden('Owner support is not configured.')
    try:
        data=signing.loads(request.POST.get('ticket',''),key=secret,salt='tenant-owner-support',max_age=30,fallback_keys=[])
        if data['tenant']!=key or not isinstance(data['reason'],str) or not data['reason'].strip() or not isinstance(data['owner'],str) or len(data['owner'])>160:raise ValueError
        nonce=uuid.UUID(data['nonce'])
        with transaction.atomic():
            user=User(username='owner-support-'+nonce.hex,role='admin',is_superuser=True,is_staff=True)
            user.set_unusable_password();user.save()
            receipt=OwnerSupportReceipt.objects.create(nonce=nonce,user=user,owner_reference=data['owner'],reason=data['reason'][:250],expires_at=timezone.now()+timedelta(minutes=30))
            record(user,'owner_support_accepted',receipt.reason)
    except (signing.BadSignature,ValueError,KeyError,TypeError,IntegrityError):return HttpResponseForbidden('Invalid, expired or replayed support authorization.')
    login(request,user,backend='django.contrib.auth.backends.ModelBackend');request.session['owner_support_receipt']=receipt.pk
    return redirect('owner-control')

@login_required
@never_cache
def sessions(request):
    from .setup_views import admin_role
    admin_role(request.user)
    if request.method=='POST':
        with transaction.atomic():
            row=get_object_or_404(OwnerSupportReceipt.objects.select_for_update(),pk=request.POST.get('receipt'))
            row.revoked_at=timezone.now();row.save(update_fields=['revoked_at'])
            record(row.user,'owner_support_revoked','Tenant administrator ended support',request.user)
        return redirect('owner-support-sessions')
    return render(request,'accounts/support_sessions.html',{'sessions':OwnerSupportReceipt.objects.select_related('user').order_by('-pk')[:100]})
