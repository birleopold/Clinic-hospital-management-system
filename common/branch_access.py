from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone
from apps.accounts.models import Facility, FacilityAccess


def facilities(user):
    from django.db.models import Q
    if user.is_superuser:return Facility.objects.filter(is_active=True)
    home=getattr(getattr(user,'staff_profile',None),'facility_id',None)
    ids=FacilityAccess.objects.filter(user=user,revoked_at__isnull=True,expires_at__gt=timezone.now()).values_list('facility_id',flat=True) if user.role in ('admin','manager','reception') else []
    return Facility.objects.filter(Q(pk=home)|Q(pk__in=ids),is_active=True).distinct()


def apply(user,pk):
    try:pk=int(pk)
    except (ValueError,TypeError):raise PermissionDenied('Invalid facility selection.')
    if not facilities(user).filter(pk=pk).exists():raise PermissionDenied('Facility access expired or was revoked. Select your home facility.')
    user._active_facility_id=pk


class BranchScopeMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if request.user.is_authenticated and request.session.get('active_facility_id') and not request.path.startswith(('/accounts/login','/accounts/logout','/accounts/facility','/accounts/mfa','/accounts/password','/admin/')):
            try:apply(request.user,request.session['active_facility_id'])
            except PermissionDenied as exc:return JsonResponse({'detail':str(exc),'selection_url':'/accounts/facility/'},status=403)
        return self.get_response(request)
