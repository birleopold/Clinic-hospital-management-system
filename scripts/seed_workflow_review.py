"""Synthetic UI-review seed. Run only on a disposable, migrated database."""
import os,sys,json,uuid
from pathlib import Path
if '--confirm-disposable' not in sys.argv:raise SystemExit('Pass --confirm-disposable on an isolated test database.')
sys.path.insert(0,os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.base')
import django
django.setup()
from django.utils import timezone
from datetime import timedelta
from django.core import signing
from apps.accounts.models import User,Facility,StaffProfile,Department,FacilityConfiguration
from apps.operations.models import OperatingBudget,OperatingExpense,PortalGrant,PortalRecipient,ServiceRoom,FacilityAsset,DiagnosticTemplate,Admission,Bed
from apps.demographics.models import Patient
from apps.appointments.models import Appointment
from apps.orders.models import Order
from common.service_policy import SERVICES
from apps.operations import diagnostic_services,settlement_services
from django.db import transaction

@transaction.atomic
def seed():
    if User.objects.filter(username='ui-admin').exists():raise SystemExit('Synthetic users already exist. Use a fresh disposable database.')
    now=timezone.now()
    f=Facility.objects.create(name='Synthetic UI Test Clinic')
    d=Department.objects.create(facility=f,name='Synthetic outpatient department')
    def user(name,role,owner=False):
        u=User.objects.create_user(username='ui-'+name,password='Synthetic-UI-Review-789!',role=role,is_superuser=owner,is_staff=owner)
        StaffProfile.objects.update_or_create(user=u,defaults={'facility':f,'department':d})
        return u
    admin=user('admin','admin');manager=user('manager','manager');reviewer=user('reviewer','manager');doctor=user('doctor','clinician');reception=user('reception','reception');owner=user('owner','admin',True)
    conf=FacilityConfiguration.objects.create(facility=f,service_type='hospital',display_name='Synthetic UI Test Clinic',enabled_services=list(SERVICES),configured_by=admin,print_footer='Synthetic acceptance review',contact_phone='Synthetic contact')
    p=Patient.objects.create(facility=f,first_name='Synthetic',last_name='UI Patient',gender='F')
    budget=OperatingBudget.objects.create(facility=f,cost_centre='Test department',starts_on=timezone.localdate(),ends_on=timezone.localdate()+timedelta(days=30),amount=1000,status='approved',created_by=manager,reviewed_by=reviewer)
    expense=OperatingExpense.objects.create(budget=budget,incurred_on=timezone.localdate(),payee='Synthetic test supplier',reference='UI-EXP-1',description='Test reviewed cost',amount=800,status='approved',created_by=manager,reviewed_by=reviewer)
    settlement=settlement_services.record_settlement(manager,expense.pk,amount=__import__('decimal').Decimal(300),paid_on=timezone.localdate(),method='bank',account_reference='Synthetic account',transaction_reference='UI-TX-1',evidence='Synthetic statement evidence',request_key=uuid.uuid4())
    grant=PortalGrant.objects.create(patient=p,created_by=reception,expires_at=now+timedelta(days=1))
    PortalRecipient.objects.create(grant=grant,created_by=reception,recipient_name='Verified test patient',relationship='patient',verification_reference='Synthetic identity review',allow_appointment_requests=True,scopes=['visits','results','medicines','billing','appointments','feedback','instructions'])
    token=signing.dumps({'p':p.pk,'g':str(grant.key)},salt='patient-portal')
    appointment=Appointment.objects.create(patient=p,clinician=doctor,scheduled_for=now+timedelta(days=2))
    room=ServiceRoom.objects.create(facility=f,name='Synthetic imaging room',directions='First floor, room 3')
    asset=FacilityAsset.objects.create(facility=f,tag='UI-SCAN',name='Synthetic scanner',location='Room 3',custodian=manager,created_by=manager)
    template=DiagnosticTemplate.objects.create(facility=f,name='Synthetic approved preparation',version=1,order_type='imaging',fields=[{'key':'finding','label':'Finding','type':'text'}],patient_instructions='Synthetic facility-approved preparation text for UI review only.',instruction_language='English',instruction_reference='Test SOP 1',status='published',created_by=admin,reviewed_by=doctor)
    order=Order.objects.create(patient=p,order_type='imaging',code='TEST-SCAN')
    work=diagnostic_services.schedule(order.pk,admin,doctor,'Synthetic scan',now+timedelta(days=1),'Reviewed source reference',1,room=room,asset=asset,instruction_template=template)
    bed=Bed.objects.create(facility=f,ward='Synthetic',name='Bed 1')
    admission=Admission.objects.create(patient=p,bed=bed,created_by=doctor,reason='Synthetic admission',discharged_at=now,discharge_summary='Synthetic clinician-written discharge summary for UI review.')
    with open(os.getenv('CLINIC_UI_FIXTURE','/tmp/clinic-ui-fixture.json'),'w') as out:json.dump({'facility':f.pk,'expense':expense.pk,'settlement':settlement.pk,'patient':p.pk,'appointment':appointment.pk,'order':order.pk,'work':work.pk,'admission':admission.pk,'token':token},out)
    print('Synthetic UI fixture ready')

seed()
