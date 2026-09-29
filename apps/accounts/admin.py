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
