import json,os
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from apps.accounts.models import User,Facility,StaffProfile,FacilityConfiguration
from common.service_policy import SERVICES,PRESETS,DEPENDENCIES

class Command(BaseCommand):
    help='Initialize a fresh isolated tenant, preserving all existing installations.'
    @transaction.atomic
    def handle(self,*args,**options):
        if not getattr(settings,'TENANT_KEY',''):raise CommandError('Use isolated tenant settings.')
        if User.objects.exclude(username=getattr(settings,'ANONYMOUS_USER_NAME','AnonymousUser')).exists():
            self.stdout.write('Existing tenant retained; bootstrap never overwrites accounts or configuration.');return
        data=json.loads(os.environ['TENANT_BOOTSTRAP']);active=set(data['services'])
        if data['service_type'] not in PRESETS or not active or active-set(SERVICES) or any(set(DEPENDENCIES.get(s,[]))-active for s in active):raise CommandError('Invalid tenant services/dependencies.')
        password=os.environ['TENANT_ADMIN_PASSWORD'];user=User(username=os.environ['TENANT_ADMIN_USERNAME'],role='admin',mfa_required=True)
        validate_password(password,user);user.full_clean(exclude=['password','last_login','date_joined']);user.set_password(password);user.save()
        f=Facility.objects.create(name=data['name']);StaffProfile.objects.update_or_create(user=user,defaults={'facility':f})
        FacilityConfiguration.objects.create(facility=f,display_name=data['name'],service_type=data['service_type'],enabled_services=sorted(active),configured_by=user)
        self.stdout.write('Tenant administrator and selected services initialized. Credentials are not printed.')
