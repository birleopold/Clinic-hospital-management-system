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
