"""Create two disposable loopback-only apps and run the sandboxed browser review.

No existing database, credentials, .env file, tenant runtime, or external provider
is used. Settings, databases, private media, and authentication data are created
under a private temporary directory and removed on success or failure.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = '''from config.settings.base import *
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ['BROWSER_CI_DATABASE']}}
MEDIA_ROOT = Path(os.environ['BROWSER_CI_MEDIA'])
STATIC_ROOT = Path(os.environ['BROWSER_CI_STATIC'])
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1']
# HTTP is confined to the disposable loopback listener; production is unchanged.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_NAME = 'browser_ci_' + os.environ['BROWSER_CI_KIND']
CSRF_COOKIE_NAME = SESSION_COOKIE_NAME + '_csrf'
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
CSRF_TRUSTED_ORIGINS = []
REQUIRE_ADMIN_MFA = True
REQUIRE_SERVICE_SETUP = True
# This clinic UI is independent, not a deployed runtime controlled by a heartbeat.
TENANT_KEY = ''
TENANT_CONTROL_ORIGIN = ''
TENANT_SUPPORT_SECRET = ''
OWNER_CONTROL_PLANE = os.environ['BROWSER_CI_KIND'] == 'owner'
TENANT_PUBLIC_ORIGIN = 'https://synthetic-owner.example.test'
INTEGRATIONS_SMS_BACKEND = 'apps.integrations.backends.NoOpSmsBackend'
INTEGRATIONS_MOMO_BACKEND = 'apps.integrations.backends.NoOpMoMoBackend'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
TIME_ZONE = 'UTC'
'''
SERVER = '''import os
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from config.wsgi import application
class Server(ThreadingMixIn, WSGIServer):
    daemon_threads = True
class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass
server = make_server('127.0.0.1', 0, application, server_class=Server, handler_class=QuietHandler)
from pathlib import Path
Path(os.environ['BROWSER_CI_PORT_FILE']).write_text(str(server.server_port))
server.serve_forever()
'''
SEED = '''import django, json, os
from pathlib import Path
django.setup()
from django.utils import timezone
from apps.accounts.models import User, Facility, StaffProfile, FacilityConfiguration, TenantDeployment
from apps.accounts import tenant_services
from common.service_policy import SERVICES
kind = os.environ['BROWSER_CI_KIND']
facility = Facility.objects.create(name='Synthetic browser CI ' + kind)
def account(role, superuser=False):
    username = 'ci-' + kind + '-' + role
    user = User.objects.create_user(username, password=os.environ['BROWSER_CI_PASSWORD'], role=role,
        is_superuser=superuser, is_staff=superuser, mfa_required=True)
    StaffProfile.objects.create(user=user, facility=facility)
    return user
admin = account('admin', superuser=(kind == 'owner'))
FacilityConfiguration.objects.create(facility=facility, display_name=facility.name,
    service_type='hospital', enabled_services=list(SERVICES), configured_by=admin)
data = {'admin': admin.username, 'accounts': [], 'tenants': {}}
if kind == 'owner':
    for index, (label, state) in enumerate([('Active', 'active'), ('Retirement', 'suspended')]):
        row = tenant_services.create(admin, name='Synthetic CI ' + label,
            origin='https://synthetic-' + label.lower() + '.example.test', bind_port=18100 + index,
            admin_username='synthetic-admin', service_type='hospital', services=list(SERVICES))
        # Explicit fixture metadata only; no heartbeat or deployment happened.
        TenantDeployment.objects.filter(pk=row.pk).update(state=state, last_seen_at=timezone.now(),
            operator_notes='SYNTHETIC CI: last-contact and lifecycle seeded; no deployed host or TLS verification.')
        data['tenants'][label.lower()] = row.pk
else:
    for role in ('clinician', 'pharmacy', 'manager'):
        data['accounts'].append({'role': role, 'username': account(role).username})
    from apps.demographics.models import Patient
    patient = Patient.objects.create(facility=facility, first_name='Synthetic', last_name='Browser CI', gender='F')
    data['patient'] = patient.pk
Path(os.environ['BROWSER_CI_RESULT']).write_text(json.dumps(data))
'''
VERIFY = '''import django, json, os
from pathlib import Path
django.setup()
from apps.accounts.models import User, TenantDeployment, TenantSupportCase, TenantReadinessCheck
from django_otp.plugins.otp_totp.models import TOTPDevice
fixture = json.loads(Path(os.environ['BROWSER_CI_RESULT']).read_text())
fixture_usernames = [fixture['admin'], *[account['username'] for account in fixture['accounts']]]
assert len(set(fixture_usernames)) == len(fixture_usernames), 'Fixture users must be distinct'
for username in fixture_usernames:
    user = User.objects.get(username=username)
    assert user.mfa_required, 'Synthetic user must retain mandatory MFA'
    assert TOTPDevice.objects.filter(user_id=user.pk, confirmed=True).count() == 1, 'Each synthetic user must complete real MFA enrollment'
if os.environ['BROWSER_CI_KIND'] == 'owner':
    assert TenantDeployment.objects.count() == 3, 'Registration and retirement retain all tenant rows'
    retired = TenantDeployment.objects.get(name='Synthetic CI Retirement')
    assert retired.state == 'retired' and retired.activities.exists(), 'Retirement retains history'
    active = TenantDeployment.objects.get(name='Synthetic CI Active')
    assert active.state == 'active' and active.contact_name == 'Synthetic operator'
    assert active.operator_notes.startswith('SYNTHETIC CI:'), 'Synthetic contact disclaimer retained'
    assert TenantReadinessCheck.objects.get(tenant=active, step='services').status == 'verified'
    assert TenantSupportCase.objects.get(tenant=active, title='Synthetic CI support case').status == 'resolved'
    new = TenantDeployment.objects.get(name='Synthetic CI Registered')
    assert new.bundle_generated_at and not new.configuration_editable and new.state == 'provisioning'
    assert new.last_seen_at is None, 'Bundle download must not fake deployment or contact'
else:
    from apps.demographics.models import Patient
    assert Patient.objects.filter(first_name='Synthetic', last_name='Browser CI').count() == 1
    assert not TenantDeployment.objects.exists(), 'Independent clinic has no owner registry'
assert Path(os.environ['BROWSER_CI_MEDIA'], 'synthetic-marker.txt').read_text() == os.environ['BROWSER_CI_KIND']
'''


def clean_environment():
    """Do not inherit production settings, DB URLs, provider keys, or CI tokens."""
    allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'LD_LIBRARY_PATH')
    return {key: os.environ[key] for key in allowed if key in os.environ}


def python_command(arguments, env, *, label):
    result = subprocess.run([sys.executable, *arguments], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    if result.returncode:
        raise RuntimeError(f'{label} failed (exit {result.returncode}); no private process output retained')


def wait_for_server(process, port_file):
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Disposable application exited before becoming ready')
        if port_file.exists():
            port = int(port_file.read_text())
            origin = f'http://127.0.0.1:{port}'
            try:
                with opener.open(origin + '/accounts/login/', timeout=2) as response:
                    if response.status == 200:
                        return origin
            except (OSError, URLError):
                pass
        time.sleep(0.2)
    raise RuntimeError('Disposable application did not become ready within 45 seconds')


def run():
    processes = []
    # A fresh temporary root is the only possible DB/media/settings destination.
    with tempfile.TemporaryDirectory(prefix='clinic-browser-ci-') as directory:
        temp = Path(directory)
        (temp / 'browser_ci_settings.py').write_text(SETTINGS)
        (temp / 'server.py').write_text(SERVER)
        password = secrets.token_urlsafe(32)
        envs, fixture = {}, {'password': password}
        base = {**clean_environment(), 'PYTHONPATH': str(temp) + os.pathsep + str(ROOT),
                'DJANGO_SETTINGS_MODULE': 'browser_ci_settings', 'BROWSER_CI_PASSWORD': password,
                'TMPDIR': str(temp), 'PYTHONUNBUFFERED': '1'}
        try:
            for kind in ('owner', 'clinic'):
                folder = temp / kind
                folder.mkdir(mode=0o700)
                media = folder / 'media'
                media.mkdir(mode=0o700)
                (media / 'synthetic-marker.txt').write_text(kind)
                env = {**base, 'BROWSER_CI_KIND': kind, 'DJANGO_SECRET_KEY': secrets.token_urlsafe(64),
                       'BROWSER_CI_DATABASE': str(folder / 'db.sqlite3'), 'BROWSER_CI_MEDIA': str(media),
                       'BROWSER_CI_STATIC': str(folder / 'static'), 'BROWSER_CI_PORT_FILE': str(folder / 'port'),
                       'BROWSER_CI_RESULT': str(folder / 'fixture.json')}
                envs[kind] = env
                python_command(['manage.py', 'migrate', '--noinput'], env, label=kind + ' migrations')
                python_command(['manage.py', 'collectstatic', '--noinput'], env, label=kind + ' static collection')
                python_command(['-c', SEED], env, label=kind + ' synthetic seed')
                fixture[kind] = json.loads(Path(env['BROWSER_CI_RESULT']).read_text())
                process = subprocess.Popen([sys.executable, str(temp / 'server.py')], cwd=ROOT, env=env,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                processes.append(process)
                fixture[kind]['origin'] = wait_for_server(process, Path(env['BROWSER_CI_PORT_FILE']))
            assert Path(envs['owner']['BROWSER_CI_DATABASE']).stat().st_ino != Path(envs['clinic']['BROWSER_CI_DATABASE']).stat().st_ino
            fixture_path = temp / 'browser-fixture.json'
            fixture_path.write_text(json.dumps(fixture))
            fixture_path.chmod(0o600)
            result = subprocess.run(['node', str(ROOT / 'scripts/browser_ci_review.cjs')], cwd=ROOT,
                                    env={**clean_environment(), 'TMPDIR': str(temp), 'CI': '1',
                                         'BROWSER_CI_FIXTURE': str(fixture_path)}, timeout=600)
            if result.returncode:
                raise RuntimeError('Sandboxed browser review failed; see the sanitized stage above')
            for kind, env in envs.items():
                python_command(['-c', VERIFY], env, label=kind + ' persisted-state verification')
            print('PASS: independent disposable databases/media; UI writes and MFA enrollment persisted; retirement retained records; no live deployment claimed.')
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    try:
        run()
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(1)
