from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth import get_user_model
from django_otp.plugins.otp_totp.models import TOTPDevice
from common.mfa import record


class Command(BaseCommand):
    help='Privileged server-side MFA recovery after independent identity verification; revokes device-bound sessions and tokens.'
    def add_arguments(self,parser):
        parser.add_argument('username')
        parser.add_argument('--operator',required=True)
        parser.add_argument('--reason',required=True)
        parser.add_argument('--commit',action='store_true')
    @transaction.atomic
    def handle(self,*args,**options):
        User=get_user_model()
        target=User.objects.select_for_update().filter(username=options['username'],is_active=True).first()
        operator=User.objects.filter(username=options['operator'],is_active=True,is_superuser=True).first()
        reason=options['reason'].strip()
        if not target or not operator or not reason or len(reason)>250:raise CommandError('Active target, active superuser operator and evidence/reason (1–250 characters) required.')
        self.stdout.write(f'{TOTPDevice.objects.filter(user=target).count()} authenticator devices will be revoked; password is unchanged.')
        if options['commit']:
            TOTPDevice.objects.filter(user=target).delete()
            record(target,'mfa_server_reset',reason,operator)
            self.stdout.write('Devices revoked. Administrator must enroll again. Follow the facility identity-verification recovery procedure.')
