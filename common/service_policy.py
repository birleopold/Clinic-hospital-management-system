"""One catalog for service setup, discoverability and server-side module gates."""
from urllib.parse import urlsplit
from django.core.exceptions import PermissionDenied
from common.facility_scope import user_staff_facility_id

SERVICES={
 'patients':('Customer / patient registration','Identity, contacts and duplicate review'),
 'clinical':('Outpatient consultations','Clinical visits, notes, triage and referrals'),
 'appointments':('Appointments and queues','Booking, reception and service queues'),
 'pharmacy':('Pharmacy / dispensing','Prescription and permitted retail supply, baskets and returns'),
 'inventory':('Stock and purchasing','Stock counts, suppliers, purchase orders and receipts'),
 'billing':('Billing and collections','Invoices, payments, cash reconciliation and insurance'),
 'lab':('Laboratory','Specimens, laboratory worksheets, results and QC'),
 'imaging':('Imaging / scans','Radiography, ultrasound, CT and imaging reports'),
 'inpatient':('Inpatient / wards','Beds, admissions, nursing observations and medication rounds'),
 'maternity':('Maternity','Pregnancy care, labour observations, delivery and newborn records'),
 'theatre':('Theatre / surgery','Operating schedules, counts and visiting specialists'),
 'vaccination':('Vaccination','Vaccination records, corrections and adverse events'),
 'rehabilitation':('Rehabilitation','Plans, sessions and outcome measurements'),
 'programmes':('Clinical programmes','Governed definitions, enrollment and cohort reviews'),
 'engagement':('Patient engagement','Recalls, appointment requests and consented reminders'),
 'workforce':('Workforce','Staff directory, duty roster, attendance, leave and handovers'),
 'management':('Management','Incidents, equipment, budgets, checklists and operational insights'),
}
PRESETS={
 'pharmacy':['patients','pharmacy','inventory','billing'],
 'clinic':['patients','clinical','appointments','billing','management'],
 'hospital':list(SERVICES),
 'custom':['patients'],
}
DEPENDENCIES={'pharmacy':['patients','inventory','billing'],'clinical':['patients'],'appointments':['patients'],'lab':['patients'],'imaging':['patients'],'inpatient':['patients','clinical'],'maternity':['patients','clinical'],'theatre':['patients','clinical'],'vaccination':['patients','inventory'],'rehabilitation':['patients','clinical'],'programmes':['patients','clinical'],'engagement':['patients'],'billing':['patients']}

SLUG_SERVICES={}
for service,slugs in {
 'vaccination':['vaccinations','vaccine-adverse-events','vaccination-corrections'],
 'inventory':['storage-protocols','cold-chain','packages','supplier-credits','locations','counts'],
 'theatre':['theatre','perioperative','instrument-counts'],
 'maternity':['pregnancies','maternity-visits','deliveries','newborns','labour-observations'],
 'rehabilitation':['rehabilitation','rehab-sessions','rehab-outcomes'],
 'lab':['lab-panels','lab-analytes','specimens'],
 'inpatient':['beds','admissions','observations','administrations','inpatient-orders','care-plans'],
 'billing':['coverage','policies','remittances','collections','credits','refunds','payers','claims'],
 'appointments':['rooms','bookings'],
 'engagement':['reminders'], 'patients':['duplicates'], 'clinical':['clinical','referrals'],
}.items():
    for slug in slugs:SLUG_SERVICES[slug]=service
SLUG_SERVICES['results']='diagnostics'


def profile(user):
    if user.is_superuser and not getattr(user,'_active_facility_id',None):return None
    if hasattr(user,'_service_profile'):return user._service_profile
    from apps.accounts.models import FacilityConfiguration
    fid=user_staff_facility_id(user)
    user._service_profile=FacilityConfiguration.objects.filter(facility_id=fid).first() if fid else None
    return user._service_profile


def enabled(user,service):
    if not service:return True
    conf=profile(user)
    active=set(conf.enabled_services) if conf else set(SERVICES)
    if service=='orders':return bool(active & {'clinical','lab','imaging'})
    if service=='prescribing':return bool(active & {'clinical','pharmacy'})
    if service=='diagnostics':return bool(active & {'lab','imaging'})
    if service=='specialties':return bool(active & {'maternity','theatre','vaccination','rehabilitation'})
    return service in active


def service_for_url(url):
    path=urlsplit(url).path.rstrip('/')
    if path in ('','/suite') or path.startswith(('/accounts/','/admin/','/static/','/api/auth','/api/schema','/api/docs','/suite/setup','/suite/imports')):return None
    if path.startswith('/pharmacy/rx/'):return 'prescribing'
    if path.endswith('/handoff/') or path.endswith('/handoff'):return 'appointments'
    if path.startswith('/suite/clinical-operations/'):
        kind=path.split('/')[3]
        return 'programmes' if kind in ('programmes','enrollments','reviews') else ('imaging' if kind=='studies' else 'lab')
    if path.startswith(('/suite/specialties/','/suite/lookup/')):
        return SLUG_SERVICES.get(path.split('/')[3])
    if path.startswith('/suite/'):
        part=path.split('/')[2]
        if part in SLUG_SERVICES:return SLUG_SERVICES[part]
        mapping={'finance':'billing','returns':'pharmacy','price-reviews':'pharmacy','replenishment':'inventory','stock':'inventory','reorder-report':'inventory','diagnostics':'diagnostics','visiting':'theatre','visiting-specialists':'theatre','appointment-requests':'engagement','recalls':'engagement','outreach':'engagement','management':'management','insights':'management','workforce':'workforce','medication-round':'inpatient','specialty-follow-up':'specialties','patient':'patients','find-patient':'patients','visit':'clinical','note-templates':'clinical','documents':'clinical','insurance':'billing'}
        return mapping.get(part)
    for prefix,service in [('/pharmacy','pharmacy'),('/inventory','inventory'),('/cashier','billing'),('/billing','billing'),('/reports','billing'),('/labs','lab'),('/orders','orders'),('/ehr','clinical'),('/offline','clinical'),('/patients','patients'),('/appointments','appointments'),('/queues','appointments')]:
        if path.startswith(prefix):return service
    if path.startswith('/api/'):
        part=path.split('/')[2]
        if part.startswith('prescription'):return 'prescribing'
        if part.startswith(('dispense','backorder')):return 'pharmacy'
        if part.startswith(('inventory','batch','stock','supplier','purchase','goods')):return 'inventory'
        if part.startswith(('invoice','payment','cash','price','report')):return 'billing'
        if part.startswith(('order','result')):return 'orders'
        if part.startswith(('encounter','vital','diagnos')):return 'clinical'
        if part.startswith(('appointment','queue','availability','time-off','doctor-')):return 'appointments'
        if part.startswith('patient'):return 'patients'
    return None


def enforce(user,url):
    from django.conf import settings
    if settings.REQUIRE_SERVICE_SETUP and user_staff_facility_id(user) and not profile(user) and not urlsplit(url).path.startswith(('/accounts/','/admin/','/static/')):
        raise PermissionDenied('An administrator must complete facility setup first.')
    if not enabled(user,service_for_url(url)):
        raise PermissionDenied('This service is not enabled for the selected facility.')


# Menu roles match the destination's intended read access, independently of enabled services.
NAVIGATION=[
 ('Workspace','/suite/',None,None),
 ('Tasks','/suite/tasks/',None,None),
 ('Patients / customers','/patients','patients',['reception','clinician']),
 ('Appointments','/appointments/schedule','appointments',['reception','clinician']),
 ('Consultations','/ehr','clinical',['clinician','nurse']),
 ('Pharmacy','/pharmacy','pharmacy',['pharmacy']),
 ('Dispensing baskets','/pharmacy/baskets/','pharmacy',['pharmacy']),
 ('Stock and purchasing','/suite/stock/','inventory',['store','manager','pharmacy']),
 ('Laboratory','/labs','lab',['lab','clinician']),
 ('Imaging','/suite/diagnostics/?kind=imaging','imaging',['radiology','clinician']),
 ('Maternity','/suite/pregnancies/','maternity',['clinician','nurse']),
 ('Ward care','/suite/admissions/','inpatient',['clinician','nurse']),
 ('Theatre','/suite/theatre/','theatre',['clinician','nurse']),
 ('Vaccination','/suite/vaccinations/','vaccination',['clinician','nurse']),
 ('Rehabilitation','/suite/rehabilitation/','rehabilitation',['clinician','nurse']),
 ('Clinical programmes','/suite/clinical-operations/enrollments/','programmes',['clinician','nurse']),
 ('Cashier','/cashier','billing',['cashier']),
 ('Finance','/suite/finance/','billing',['manager','cashier']),
 ('Recalls and contact consent','/suite/recalls/','engagement',['reception','clinician','nurse']),
 ('Duty and attendance','/suite/workforce/','workforce',None),
 ('Management','/suite/management/','management',['manager']),
 ('Setup and staff','/suite/setup/',None,['admin']),
]


def navigation(user):
    return [{'label':label,'url':url,'service':service} for label,url,service,roles in NAVIGATION if enabled(user,service) and (roles is None or user.is_superuser or user.role=='admin' or user.role in roles)]


class ServiceGateMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        from django.http import HttpResponseNotFound
        if request.user.is_authenticated:
            from django.conf import settings
            from django.shortcuts import redirect
            if settings.REQUIRE_SERVICE_SETUP and request.path in ('/','/suite/'):
                if request.user.is_superuser and not getattr(request.user,'_active_facility_id',None):return redirect('owner-control')
                if not profile(request.user) and (request.user.is_superuser or request.user.role=='admin'):return redirect('facility-configure')
            try:enforce(request.user,request.path)
            except PermissionDenied:return HttpResponseNotFound('This service is not available in this workspace.')
        return self.get_response(request)


def can_open(user,url):
    if not enabled(user,service_for_url(url)):return False
    if user.is_superuser or user.role=='admin':return True
    path=urlsplit(url).path.rstrip('/')
    from django.urls import resolve,Resolver404
    try:match=resolve(urlsplit(url).path)
    except Resolver404:return False
    if match.url_name in ('suite-collection','suite-action','suite-specialty-detail','suite-lookup'):
        from apps.operations.views import MODULES
        entry=MODULES.get(match.kwargs.get('slug'))
        return bool(entry and user.role in entry[4])
    if path.startswith('/suite/diagnostics'):return user.role in ('clinician','lab','radiology')
    if path.startswith('/pharmacy/rx/'):return 'prescribing'
    if path.endswith('/handoff/') or path.endswith('/handoff'):return 'appointments'
    if path.startswith('/suite/clinical-operations/'):
        from apps.operations.extension_views import REGISTERS
        entry=REGISTERS.get(path.split('/')[3]);return bool(entry and user.role in entry[4])
    if path.startswith('/suite/management/checklists'):return True
    if path.startswith(('/suite/management','/suite/insights')):return user.role=='manager'
    if path.startswith('/suite/finance'):return user.role in ('manager','cashier')
    if path.startswith(('/suite/appointment-requests','/suite/recalls','/suite/outreach')):return user.role in ('reception','clinician','nurse')
    if path.startswith(('/accounts/setup','/accounts/staff')):return False
    if path.startswith('/suite/setup'):return user.role=='manager'
    for label,navurl,service,roles in NAVIGATION:
        if urlsplit(navurl).path.rstrip('/')==path:return roles is None or user.role in roles
    return True
