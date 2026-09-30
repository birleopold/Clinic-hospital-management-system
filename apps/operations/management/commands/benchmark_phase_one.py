"""Repeatable local-only synthetic UI benchmark; every inserted row is rolled back."""
import json
import time
import uuid
from statistics import median
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext, override_settings
from apps.accounts.models import User, Facility, StaffProfile
from apps.demographics.models import Patient
from apps.operations.models import ClinicalEntry

class Command(BaseCommand):
    help='Benchmark chart/search using rolled-back synthetic records in development/test only.'
    def add_arguments(self,parser):
        parser.add_argument('--confirm-disposable',action='store_true')
        parser.add_argument('--patients',type=int,default=5000)
        parser.add_argument('--notes',type=int,default=500)
    def handle(self,*args,**options):
        if not options['confirm_disposable'] or not settings.DEBUG:
            raise CommandError('Run only in a disposable DEBUG development database with --confirm-disposable.')
        if not 100<=options['patients']<=20000 or not 25<=options['notes']<=2000:raise CommandError('Use 100–20000 patients and 25–2000 notes.')
        with transaction.atomic(),override_settings(ALLOWED_HOSTS=['testserver']):
            facility=Facility.objects.create(name='Synthetic benchmark')
            user=User.objects.create_user(username='benchmark-'+uuid.uuid4().hex,role='clinician')
            StaffProfile.objects.update_or_create(user=user,defaults={'facility':facility})
            patients=Patient.objects.bulk_create([Patient(first_name=f'Bench{i}',last_name='Synthetic',gender='F',facility=facility) for i in range(options['patients'])])
            patient=patients[0]
            ClinicalEntry.objects.bulk_create([ClinicalEntry(patient=patient,created_by=user,kind='note',text=f'Synthetic note {i}') for i in range(options['notes'])])
            client=Client();client.force_login(user)
            report={'database':connection.vendor,'patients':options['patients'],'notes_in_chart':options['notes'],'runs_per_endpoint':20,'measurements':{}}
            for name,path in [('chart',f'/suite/patient/{patient.pk}/'),('search','/suite/find-patient/?q=Bench0')]:
                times=[];counts=[]
                for _ in range(20):
                    with CaptureQueriesContext(connection) as queries:
                        started=time.perf_counter();response=client.get(path);elapsed=(time.perf_counter()-started)*1000
                    if response.status_code!=200:raise CommandError(f'{name} failed: {response.status_code}')
                    times.append(elapsed);counts.append(len(queries))
                report['measurements'][name]={'median_ms':round(median(times),2),'p95_ms':round(sorted(times)[18],2),'max_queries':max(counts)}
            transaction.set_rollback(True)
        self.stdout.write(json.dumps(report,indent=2))
