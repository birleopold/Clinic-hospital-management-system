from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Facility, Department, StaffProfile

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + ((None, {'fields': ('role','mobile_number')}),)
    list_display = ('username','email','role','is_active','is_staff','is_superuser')

@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('id','name','code','is_active')
    search_fields = ('name','code')

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('id','name','facility','is_active')
    search_fields = ('name','code','facility__name')
    list_filter = ('facility',)

@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ('id','user','facility','department','title')
    search_fields = ('user__username','facility__name','department__name','title')

# Device secrets and reset operations are not exposed through Django admin.
from django_otp.plugins.otp_totp.models import TOTPDevice
if admin.site.is_registered(TOTPDevice):
    admin.site.unregister(TOTPDevice)

from .models import FacilityAccess, SecurityEvent

@admin.register(FacilityAccess)
class FacilityAccessAdmin(admin.ModelAdmin):
    list_display=('user','facility','expires_at','revoked_at','granted_by')
    readonly_fields=('granted_by','created_at')
    def save_model(self,request,obj,form,change):
        from common.mfa import record
        obj.granted_by=request.user
        super().save_model(request,obj,form,change)
        record(obj.user,'facility_access_changed',f'Facility {obj.facility_id}; expiry {obj.expires_at}; revoked {bool(obj.revoked_at)}',request.user)
    def has_delete_permission(self,request,obj=None):return False

@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display=('created_at','actor','target','event','reason')
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False
