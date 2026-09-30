"""Role-focused entry points; destination views remain the authorization boundary."""
from django.utils import timezone
from django.db.models import Q
from common.facility_scope import filter_by_patient_facility, filter_by_facility
from apps.encounters.models import Encounter
from apps.orders.models import OrderResult
from apps.appointments.models import Appointment
from apps.billing.models import Invoice
from apps.inventory.models import Batch
from .models import Referral, Reminder

ROLE_ACTIONS = {
 'reception': [('Find or register patient','/patients'),('Appointments','/appointments/schedule'),('Patient queues','/queues')],
 'clinician': [('My consultations','/ehr'),('Review results','/suite/results/'),('Referrals','/suite/referrals/'),('Offline drafts','/offline/')],
 'nurse': [('Triage and visits','/ehr'),('Medication round','/suite/medication-round/'),('Ward observations','/suite/observations/'),('Offline drafts','/offline/')],
 'pharmacy': [('Dispense prescriptions','/pharmacy'),('Backorders','/pharmacy/backorders'),('Stock control','/suite/stock/'),('Reorder suggestions','/suite/reorder-report/')],
 'lab': [('Laboratory worklist','/labs'),('Specimen reception','/suite/specimens/'),('Review results','/suite/results/')],
 'cashier': [('Open cashier','/cashier'),('Collections','/suite/collections/'),('Cashbook','/cashier/cashbook')],
 'manager': [('Reports','/reports'),('Stock control','/suite/stock/'),('Reorder suggestions','/suite/reorder-report/'),('Settings','/billing/settings')],
 'store': [('Stock control','/suite/stock/'),('Purchase orders','/inventory/po'),('Goods receipts','/inventory/grn'),('Reorder suggestions','/suite/reorder-report/')],
 'admin': [('Patients','/patients'),('Clinical visits','/ehr'),('Reports','/reports'),('Stock control','/suite/stock/')],
}

def workspace_context(user):
    role='admin' if user.is_superuser else user.role
    cards=[]
    def card(label,qs,url):cards.append({'label':label,'count':qs.count(),'url':url})
    clinical=role in ('admin','clinician','nurse')
    visits=filter_by_facility(Encounter.objects.filter(status='open'),user)
    if role=='clinician': visits=visits.filter(clinician=user)
    if clinical:
        card('My open visits' if role=='clinician' else 'Open visits',visits,'/ehr')
        card('Overdue referrals',filter_by_patient_facility(Referral.objects.filter(status__in=['open','accepted'],due_date__lt=timezone.localdate()),user),'/suite/referrals/?status=open')
    if role in ('admin','clinician','nurse','lab'):
        results=filter_by_patient_facility(OrderResult.objects.all(),user,prefix='order__patient__')
        card('Critical results awaiting acknowledgment',results.filter(approved_at__isnull=False,critical=True,acknowledged_at__isnull=True),'/suite/results/')
        if role in ('admin','lab'):card('Results awaiting release',results.filter(approved_at__isnull=True),'/suite/results/')
    if role in ('admin','reception'):
        card("Today's appointments",filter_by_patient_facility(Appointment.objects.filter(scheduled_for__date=timezone.localdate()).exclude(status__in=['cancelled','no_show']),user),'/appointments/schedule')
        card('Failed reminders',filter_by_patient_facility(Reminder.objects.filter(status='failed'),user),'/suite/reminders/?status=failed')
    if role in ('admin','manager','pharmacy','store'):
        card('Expired stock on hand',filter_by_facility(Batch.objects.filter(expiry__lt=timezone.localdate(),quantity_on_hand__gt=0),user,field='location__facility_id'),'/suite/stock/')
    if role in ('admin','cashier','manager'):
        card('Invoices awaiting payment',filter_by_patient_facility(Invoice.objects.filter(status='ready_to_pay'),user),'/cashier' if role!='manager' else '/reports')
    from .workflow_views import task_scope
    assigned=task_scope(user).filter(owner=user,status__in=['open','in_progress']).select_related('patient').order_by('due_at')[:10]
    return {'assigned_tasks':assigned,'role_title':role.title(),'role_actions':[{'label':a,'url':b} for a,b in ROLE_ACTIONS.get(role,[])],'attention_cards':cards,'visits':visits.select_related('patient','clinician').order_by('started_at')[:50] if clinical else [],'show_visits':clinical}
