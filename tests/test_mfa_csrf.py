"""Exercise MFA with real CSRF checks; Django's default test client skips them."""
import pytest
from django.test import Client
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice


pytestmark = pytest.mark.django_db
PASSWORD = 'Synthetic-mfa-password-123'
ENROLL = '/accounts/mfa/enroll/'
VERIFY = '/accounts/mfa/'


@pytest.fixture
def mfa_client(django_user_model, settings):
    settings.REQUIRE_ADMIN_MFA = True
    settings.CSRF_TRUSTED_ORIGINS = []
    user = django_user_model.objects.create_user(
        username='csrf-mfa-admin', password=PASSWORD, role='admin',
        is_staff=True, is_superuser=True,
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    return client, user


def csrf_payload(client, **values):
    return {'csrfmiddlewaretoken': client.cookies['csrftoken'].value, **values}


def assert_private_form(response):
    assert response.status_code == 200
    # This is the browser-side regression: no-referrer makes native POST origins
    # opaque even on a direct, same-origin browser tab.
    assert response['Referrer-Policy'] == 'same-origin'
    assert 'no-store' in response['Cache-Control']
    assert b'name="csrfmiddlewaretoken"' in response.content


@pytest.mark.parametrize('secure,send_origin', [
    (False, True), (True, True), (True, False),
])
def test_enrollment_preserves_same_origin_csrf(mfa_client, secure, send_origin):
    client, user = mfa_client
    origin = ('https' if secure else 'http') + '://testserver'
    headers = {'HTTP_ORIGIN': origin} if send_origin else {
        'HTTP_REFERER': origin + ENROLL,
    }
    assert_private_form(client.get(ENROLL, secure=secure))

    invalid = client.post(
        ENROLL, csrf_payload(client, password='wrong'), secure=secure, **headers,
    )
    assert_private_form(invalid)
    assert not TOTPDevice.objects.filter(user=user).exists()

    started = client.post(
        ENROLL, csrf_payload(client, password=PASSWORD), secure=secure, **headers,
    )
    assert started.status_code == 302 and started.url == ENROLL
    device = TOTPDevice.objects.get(user=user, confirmed=False)
    qr_page = client.get(ENROLL, secure=secure)
    assert_private_form(qr_page)
    assert qr_page.context['qr']

    completed = client.post(
        ENROLL, csrf_payload(client, token=f'{totp(device.bin_key):06d}'),
        secure=secure, **headers,
    )
    assert completed.status_code == 302 and completed.url == '/suite/'
    device.refresh_from_db()
    user.refresh_from_db()
    assert device.confirmed and user.mfa_required
    assert str(client.session['otp_device_id']) == device.persistent_id


@pytest.mark.parametrize('stage', ['password', 'enrollment-code', 'verification-code'])
@pytest.mark.parametrize('attack', ['null-origin', 'foreign-origin', 'missing-token'])
def test_mfa_keeps_csrf_enforcement(mfa_client, stage, attack):
    client, user = mfa_client
    device = None
    path = ENROLL
    values = {'password': PASSWORD}
    if stage == 'enrollment-code':
        client.get(ENROLL)
        started = client.post(
            ENROLL, csrf_payload(client, password=PASSWORD),
            HTTP_ORIGIN='http://testserver',
        )
        assert started.status_code == 302
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        values = {'token': f'{totp(device.bin_key):06d}'}
    elif stage == 'verification-code':
        path = VERIFY
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        values = {'token': f'{totp(device.bin_key):06d}'}
    assert_private_form(client.get(path, secure=True))

    headers = {'HTTP_ORIGIN': 'https://testserver'}
    payload = csrf_payload(client, **values)
    if attack == 'missing-token':
        payload.pop('csrfmiddlewaretoken')
    else:
        headers['HTTP_ORIGIN'] = (
            'null' if attack == 'null-origin' else 'https://untrusted.example'
        )
    response = client.post(path, payload, secure=True, **headers)
    assert response.status_code == 403
    assert 'otp_device_id' not in client.session
    if device is None:
        assert not TOTPDevice.objects.filter(user=user).exists()
    else:
        device.refresh_from_db()
        assert device.confirmed == (stage == 'verification-code')
        assert device.last_t == -1
