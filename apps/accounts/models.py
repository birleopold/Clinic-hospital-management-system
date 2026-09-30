from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ADMIN = 'admin'
    RECEPTION = 'reception'
    NURSE = 'nurse'
    CLINICIAN = 'clinician'
    LAB = 'lab'
    PHARMACY = 'pharmacy'
    CASHIER = 'cashier'
    MANAGER = 'manager'
    STORE = 'store'
    RADIOLOGY = 'radiology'

    ROLE_CHOICES = [
        (ADMIN, 'Admin'),
        (RECEPTION, 'Reception'),
        (NURSE, 'Nurse'),
        (CLINICIAN, 'Clinician'),
        (LAB, 'Lab'),
        (PHARMACY, 'Pharmacy'),
        (CASHIER, 'Cashier'),
        (MANAGER, 'Manager'),
        (STORE, 'Store / inventory'),
        (RADIOLOGY, 'Radiography / imaging operator'),
    ]

    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=RECEPTION)
    mfa_required = models.BooleanField(default=False)
    mobile_number = models.CharField(max_length=64, blank=True)

class Facility(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Department(models.Model):
    facility = models.ForeignKey('accounts.Facility', on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.facility})"

class StaffProfile(models.Model):
    user = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='staff_profile')
    facility = models.ForeignKey('accounts.Facility', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff')
    department = models.ForeignKey('accounts.Department', on_delete=models.SET_NULL, null=True, blank=True, related_name='staff')
    title = models.CharField(max_length=128, blank=True)

    def __str__(self):
        return f"{self.user} @ {self.facility or 'Unassigned'}"


class SecurityEvent(models.Model):
    actor = models.ForeignKey(User,on_delete=models.PROTECT,related_name='+')
    target = models.ForeignKey(User,on_delete=models.PROTECT,related_name='+')
    event = models.CharField(max_length=60)
    reason = models.CharField(max_length=250,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class FacilityAccess(models.Model):
    user = models.ForeignKey(User,on_delete=models.PROTECT,related_name='facility_access')
    facility = models.ForeignKey(Facility,on_delete=models.PROTECT)
    expires_at = models.DateTimeField()
    reason = models.CharField(max_length=250)
    granted_by = models.ForeignKey(User,on_delete=models.PROTECT,related_name='+')
    revoked_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['user','facility'],name='unique_staff_facility_access')]
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.user.role not in ('admin','manager','reception'):
            raise ValidationError('Branch switching is limited to administration, management and reception. Clinical duty privileges require separate credentialing.')


class FacilityConfiguration(models.Model):
    facility=models.OneToOneField(Facility,on_delete=models.PROTECT,related_name='configuration')
    service_type=models.CharField(max_length=20,choices=[('pharmacy','Pharmacy only'),('clinic','Clinic'),('hospital','Hospital'),('custom','Custom services')])
    display_name=models.CharField(max_length=160)
    tagline=models.CharField(max_length=250,blank=True)
    contact_phone=models.CharField(max_length=40,blank=True)
    logo=models.FileField(upload_to='private/branding/', blank=True)
    receipt_paper=models.CharField(max_length=16,default='a4',choices=[('a4','A4'),('80mm','Thermal 80mm')])
    print_footer=models.CharField(max_length=250,blank=True)
    enabled_services=models.JSONField(default=list)
    configured_by=models.ForeignKey(User,on_delete=models.PROTECT,related_name='+')
    updated_at=models.DateTimeField(auto_now=True)
    revision=models.PositiveIntegerField(default=1)
