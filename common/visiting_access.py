from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from drf_spectacular.extensions import OpenApiAuthenticationExtension


def restricted(user):
    if not user or not user.is_authenticated:return False
    from apps.operations.models import VisitingSpecialist
    return VisitingSpecialist.objects.filter(user_id=user.pk).exists()


class VisitingAccessMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if restricted(request.user) and not (request.path.startswith('/suite/visiting/') or request.path.rstrip('/')=='/accounts/logout' or request.path.startswith('/static/')):
            if request.method in ('GET','HEAD') and not request.path.startswith('/api/'):return redirect('visiting-portal')
            return HttpResponseForbidden('Visiting specialist accounts use their assigned-case portal only.')
        return self.get_response(request)


class StaffJWTAuthentication(JWTAuthentication):
    def authenticate(self,request):
        result=super().authenticate(request)
        if result:
            from apps.accounts.token_views import support_account
            if support_account(result[0]):raise AuthenticationFailed('Owner support uses its expiring browser session only.')
        if result and restricted(result[0]):raise AuthenticationFailed('Visiting specialist accounts cannot use the general staff API.')
        if result:
            from .mfa import required, device_valid
            if (required(result[0]) or result[1].get('mfa_device_id')) and not device_valid(result[0],result[1].get('mfa_device_id')):
                raise AuthenticationFailed('Sign in again with your authenticator.')
        if result and request.headers.get('X-Clinic-Facility'):
            from .branch_access import apply
            from django.core.exceptions import PermissionDenied
            try:apply(result[0],request.headers['X-Clinic-Facility'])
            except PermissionDenied as exc:raise AuthenticationFailed(str(exc))
        if result:
            from .service_policy import enforce
            enforce(result[0],request.path)
        return result


class StaffJWTScheme(OpenApiAuthenticationExtension):
    target_class='common.visiting_access.StaffJWTAuthentication'
    name='jwtAuth'
    def get_security_definition(self,auto_schema):
        return {'type':'http','scheme':'bearer','bearerFormat':'JWT'}
