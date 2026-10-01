from django.contrib.auth import get_user_model
from django.views.decorators.debug import sensitive_variables, sensitive_post_parameters
from django.utils.decorators import method_decorator
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from common.mfa import required, verify, device_valid, record
from common.visiting_access import restricted

def support_account(user):
    from .models import OwnerSupportReceipt
    return bool(user and OwnerSupportReceipt.objects.filter(user=user).exists())


class StaffTokenSerializer(TokenObtainPairSerializer):
    otp_token=serializers.CharField(required=False,write_only=True,max_length=6)

    @sensitive_variables('attrs','token','data','device','refresh')
    def validate(self,attrs):
        token=attrs.pop('otp_token','')
        data=super().validate(attrs)
        if support_account(self.user):raise AuthenticationFailed('Owner support uses its expiring browser session only.')
        if restricted(self.user):raise AuthenticationFailed('Use the assigned-case portal.')
        if required(self.user):
            device=verify(self.user,token)
            if not device:
                record(self.user,'mfa_api_failed')
                raise AuthenticationFailed('A valid authenticator code is required. Enroll through the staff website first.')
            refresh=self.get_token(self.user)
            refresh['mfa_device_id']=device.pk
            data={'refresh':str(refresh),'access':str(refresh.access_token)}
            record(self.user,'mfa_api_verified')
        return data


class StaffRefreshSerializer(TokenRefreshSerializer):
    @sensitive_variables('attrs','token','data','device','refresh')
    def validate(self,attrs):
        refresh=self.token_class(attrs['refresh'])
        user=get_user_model().objects.filter(pk=refresh.get('user_id'),is_active=True).first()
        if not user or support_account(user) or restricted(user) or ((required(user) or refresh.get('mfa_device_id')) and not device_valid(user,refresh.get('mfa_device_id'))):
            raise AuthenticationFailed('Sign in again with your authenticator.')
        return super().validate(attrs)


@method_decorator(sensitive_post_parameters('password','otp_token'),name='dispatch')
class StaffTokenView(TokenObtainPairView):serializer_class=StaffTokenSerializer
class StaffRefreshView(TokenRefreshView):serializer_class=StaffRefreshSerializer
