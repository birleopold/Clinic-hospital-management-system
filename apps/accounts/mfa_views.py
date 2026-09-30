import base64
import io
import time
import qrcode
from qrcode.image.svg import SvgPathImage
from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from common.mfa import verify, record


class VerifyForm(forms.Form):
    token=forms.RegexField(r'^\d{6}$',max_length=6,label='Authenticator code',widget=forms.TextInput(attrs={'inputmode':'numeric','autocomplete':'one-time-code'}))


class EnrollmentForm(forms.Form):
    password=forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}),label='Current password')


@login_required
@never_cache
@sensitive_post_parameters('password','token')
@sensitive_variables('device','form','qr','key','pending')
def challenge(request):
    if not TOTPDevice.objects.filter(user=request.user,confirmed=True).exists():
        return redirect('mfa-enroll')
    form=VerifyForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        device=verify(request.user,form.cleaned_data['token'])
        if device:
            request.session.cycle_key();otp_login(request,device);record(request.user,'mfa_verified')
            return redirect('suite-home')
        record(request.user,'mfa_failed')
        form.add_error('token','Invalid, previously used or temporarily throttled code. Wait for a new code and try again.')
    return render(request,'accounts/mfa.html',{'form':form,'title':'Verify your authenticator'})


@login_required
@never_cache
@sensitive_post_parameters('password','token')
@sensitive_variables('device','form','qr','key','pending')
def enroll(request):
    if TOTPDevice.objects.filter(user=request.user,confirmed=True).exists():return redirect('mfa-verify')
    now=time.time()
    pending=request.session.get('mfa_enrollment',{})
    device=TOTPDevice.objects.filter(pk=pending.get('id'),user=request.user,confirmed=False).first() if pending.get('until',0)>now else None
    form=VerifyForm(request.POST or None) if device else EnrollmentForm(request.POST or None)
    qr=None;key=None
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if TOTPDevice.objects.filter(user=request.user,confirmed=True).exists():return redirect('mfa-verify')
            if device:
                device=TOTPDevice.objects.select_for_update().get(pk=device.pk,user=request.user,confirmed=False)
                if device.verify_token(form.cleaned_data['token']):
                    device.confirmed=True;device.save(update_fields=['confirmed'])
                    get_user_model().objects.filter(pk=request.user.pk).update(mfa_required=True)
                    request.session.pop('mfa_enrollment',None);request.session.cycle_key();otp_login(request,device)
                    record(request.user,'mfa_enrolled')
                    return redirect('suite-home')
                record(request.user,'mfa_enrollment_failed')
                form.add_error('token','Invalid or temporarily throttled code. Wait and try again.')
            elif request.user.check_password(form.cleaned_data['password']):
                TOTPDevice.objects.filter(user=request.user,confirmed=False).delete()
                device=TOTPDevice.objects.create(user=request.user,name='Staff authenticator',confirmed=False)
                request.session['mfa_enrollment']={'id':device.pk,'until':now+600}
                record(request.user,'mfa_enrollment_started')
                return redirect('mfa-enroll')
            else:
                record(request.user,'mfa_password_failed')
                form.add_error('password','Incorrect password.')
    if device:
        image=qrcode.make(device.config_url,image_factory=SvgPathImage);buffer=io.BytesIO();image.save(buffer)
        qr=base64.b64encode(buffer.getvalue()).decode()
        key=base64.b32encode(device.bin_key).decode()
    response=render(request,'accounts/mfa.html',{'form':form,'title':'Set up your authenticator','qr':qr,'key':key})
    response['Referrer-Policy']='no-referrer'
    return response
