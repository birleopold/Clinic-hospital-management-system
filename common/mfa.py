"""Authenticator verification shared by session and JWT entry points."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django_otp.plugins.otp_totp.models import TOTPDevice


def required(user):
    return bool(user.is_authenticated and (user.mfa_required or (settings.REQUIRE_ADMIN_MFA and (user.is_superuser or user.role == 'admin')) or TOTPDevice.objects.filter(user=user,confirmed=True).exists()))


def device_valid(user, pk):
    return bool(pk and TOTPDevice.objects.filter(pk=pk,user=user,confirmed=True).exists())


@transaction.atomic
def verify(user, token):
    get_user_model().objects.select_for_update().get(pk=user.pk)
    device=TOTPDevice.objects.select_for_update().filter(user=user,confirmed=True).first()
    if device and device.verify_token(token):
        return device
    return None


def record(user,event,reason='',actor=None):
    from apps.accounts.models import SecurityEvent
    SecurityEvent.objects.create(actor=actor or user,target=user,event=event,reason=reason)


class MFAGateMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        path=request.path
        exempt=path.startswith('/accounts/mfa/') or path in ('/accounts/login/','/accounts/logout/','/admin/login/','/admin/logout/') or path.startswith('/static/')
        if request.user.is_authenticated and not exempt and required(request.user):
            device=getattr(request.user,'otp_device',None)
            if not device or not device.confirmed:
                if path.startswith('/api/') or request.method not in ('GET','HEAD'):
                    return JsonResponse({'detail':'Authenticator verification required.','verification_url':'/accounts/mfa/'},status=403)
                return redirect('mfa-verify')
        return self.get_response(request)
