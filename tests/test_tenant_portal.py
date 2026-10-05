"""Owner portal regressions; tenancy remains a physical deployment boundary."""

import io
import importlib
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts import tenant_portal_services as portal
from apps.accounts import tenant_services as control
from apps.accounts.models import (
    OwnerSupportReceipt,
    TenantActivity,
    TenantDeployment,
    TenantReadinessCheck,
    TenantSupportCase,
    User,
)
from apps.accounts.tenant_portal_forms import CaseForm
from apps.accounts.tenant_portal_models import CHECKPOINTS
from common import tenant_runtime
from common.service_policy import PRESETS

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(settings):
    settings.OWNER_CONTROL_PLANE = True
    settings.TENANT_KEY = ''
    settings.TENANT_PUBLIC_ORIGIN = 'https://owner.example.test'
    settings.REQUIRE_ADMIN_MFA = False
    settings.REQUIRE_SERVICE_SETUP = False
    cache.clear()
    return User.objects.create_user('portal-owner', is_superuser=True, role='admin')


def configuration(index=1, **overrides):
    data = {
        'name': f'Synthetic business {index}',
        'origin': f'https://tenant-{index}.example.test',
        'bind_port': 18100 + index,
        'admin_username': f'tenant-admin-{index}',
        'service_type': 'custom',
        'services': ['patients'],
    }
    return {**data, **overrides}


@pytest.fixture
def tenant(owner):
    return control.create(owner, **configuration())


def metadata(**overrides):
    return {
        'contact_name': 'Synthetic Operations Contact',
        'contact_email': 'operations@example.test',
        'contact_phone': '+1 555 0100',
        'deployment_label': 'Synthetic isolated host A',
        'operator_notes': 'Synthetic installation reference; no secrets.',
        **overrides,
    }


def case_data(**overrides):
    return {
        'title': 'Synthetic setup assistance',
        'category': 'onboarding',
        'priority': 'normal',
        'detail': 'Verify the isolated synthetic deployment setup.',
        **overrides,
    }


def case_update(**overrides):
    return {
        'status': 'open', 'priority': 'normal', 'assignee': None,
        'resolution': '', 'note': 'Synthetic operator update.', **overrides,
    }


def detail_url(tenant):
    return reverse('tenant-detail', args=[tenant.pk])


def case_url(tenant, case):
    return reverse('tenant-support-case', args=[tenant.pk, case.pk])


def policy_ticket(tenant):
    return signing.dumps(
        {'tenant': str(tenant.key), 'nonce': str(uuid.uuid4())},
        key=control.secrets_for(tenant)['support'], salt='tenant-policy-request',
    )


def mark_ready(tenant, owner):
    """Arrange recorded checks without claiming any real infrastructure is ready."""
    for step, _ in CHECKPOINTS:
        TenantReadinessCheck.objects.create(
            tenant=tenant, step=step, status='verified',
            evidence='Synthetic operator attestation.', updated_by=owner,
        )


def test_owner_home_routes_to_portal_only_on_owner_deployment(client, owner):
    client.force_login(owner)
    assert client.get('/accounts/control/').url == reverse('tenant-console')
    with override_settings(OWNER_CONTROL_PLANE=False):
        assert client.get('/accounts/control/').status_code == 200
        assert client.get(reverse('tenant-console')).status_code == 403
    with override_settings(TENANT_KEY=str(uuid.uuid4())), patch.object(
        tenant_runtime, 'policy_active', return_value=True,
    ):
        assert client.get('/accounts/control/').status_code == 200
        assert client.get(reverse('tenant-console')).status_code == 403


def test_registry_and_case_routes_require_platform_owner(client, owner, tenant):
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data())
    urls = [reverse('tenant-console'), reverse('tenant-support-queue'), detail_url(tenant), case_url(tenant, case)]
    for url in urls:
        assert client.get(url).status_code == 302
    for role in ('admin', 'manager', 'reception'):
        user = User.objects.create_user(f'ordinary-{role}', role=role)
        client.force_login(user)
        for url in urls:
            assert client.get(url).status_code == 403
        with pytest.raises(PermissionDenied):
            portal.update_metadata(user, tenant.pk, tenant.revision, uuid.uuid4(), **metadata())


@pytest.mark.parametrize('field,value', [('is_active', False), ('is_superuser', False)])
def test_owner_permissions_recheck_stored_user_even_with_stale_actor(owner, tenant, field, value):
    User.objects.filter(pk=owner.pk).update(**{field: value})
    # The in-memory actor still has the old permissions.
    with pytest.raises(PermissionDenied):
        portal.update_metadata(owner, tenant.pk, tenant.revision, uuid.uuid4(), **metadata())
    tenant.refresh_from_db()
    assert not tenant.contact_name


def test_temporary_support_identity_is_never_platform_owner(owner, tenant):
    support = User.objects.create_user('temporary-support', is_superuser=True, role='admin')
    OwnerSupportReceipt.objects.create(
        nonce=uuid.uuid4(), user=support, owner_reference=str(owner.pk),
        reason='Synthetic support', expires_at=timezone.now() + timedelta(minutes=30),
    )
    with pytest.raises(PermissionDenied):
        control.owner(support)
    with pytest.raises(PermissionDenied):
        portal.create_case(support, tenant.pk, uuid.uuid4(), **case_data())
    assert support not in portal.owner_assignees()


@pytest.mark.parametrize('preset', ['pharmacy', 'clinic', 'hospital', 'custom'])
def test_preset_registration_preserves_explicit_service_selection(client, owner, preset):
    client.force_login(owner)
    page = client.get(reverse('tenant-console'), {'preset': preset})
    assert page.context['form'].initial['services'] == PRESETS[preset]
    data = configuration(service_type=preset, services=PRESETS[preset])
    response = client.post(reverse('tenant-console'), data)
    tenant = TenantDeployment.objects.get()
    assert response.status_code == 302 and response.url == detail_url(tenant)
    assert tenant.services == sorted(PRESETS[preset])
    assert tenant.state == 'provisioning' and tenant.last_seen_at is None
    assert tenant.activities.filter(event='tenant_registered').count() == 1
    assert client.post(reverse('tenant-console'), data).status_code == 200
    assert TenantDeployment.objects.count() == 1


def test_registry_search_filters_attention_and_distinct_counts(client, owner, tenant):
    now = timezone.now()
    TenantDeployment.objects.filter(pk=tenant.pk).update(state='active', last_seen_at=now)
    mark_ready(tenant, owner)
    incomplete = control.create(owner, **configuration(2))
    stale = control.create(owner, **configuration(3))
    TenantDeployment.objects.filter(pk=stale.pk).update(
        state='active', last_seen_at=now - timedelta(minutes=11),
    )
    mark_ready(stale, owner)
    case_tenant = control.create(owner, **configuration(4))
    TenantDeployment.objects.filter(pk=case_tenant.pk).update(
        state='active', last_seen_at=now, contact_name='Needle Contact',
        contact_email='needle@example.test', deployment_label='Needle Host',
    )
    mark_ready(case_tenant, owner)
    for index in range(2):
        portal.create_case(owner, case_tenant.pk, uuid.uuid4(), **case_data(title=f'Case {index}'))
    retired = control.create(owner, **configuration(5))
    TenantDeployment.objects.filter(pk=retired.pk).update(state='retired')
    client.force_login(owner)
    response = client.get(reverse('tenant-console'), {'attention': '1'})
    rows = {row.pk: row for row in response.context['tenants']}
    assert set(rows) == {incomplete.pk, stale.pk, case_tenant.pk}
    assert rows[case_tenant.pk].ready_count == len(CHECKPOINTS)
    assert rows[case_tenant.pk].open_cases == 2
    assert response.context['stats'] == {
        'total': 5, 'open_cases': 2, 'provisioning': 1, 'active': 3,
        'suspended': 0, 'retired': 1,
    }
    for term in ('Needle Contact', 'needle@example.test', 'Needle Host', 'tenant-4'):
        result = client.get(reverse('tenant-console'), {'q': term})
        assert [row.pk for row in result.context['tenants']] == [case_tenant.pk]
    filtered = client.get(reverse('tenant-console'), {'state': 'retired'})
    assert [row.pk for row in filtered.context['tenants']] == [retired.pk]
    empty = client.get(reverse('tenant-console'), {'q': 'No matching synthetic name'})
    assert empty.context['tenants'].paginator.count == 0
    invalid = client.get(reverse('tenant-console'), {'state': 'invented'})
    assert invalid.context['state'] == ''
    assert invalid.context['tenants'].paginator.count == 5


def test_registry_pagination_keeps_filters(client, owner):
    for index in range(1, 27):
        control.create(owner, **configuration(index, name=f'Synthetic group {index:02d}'))
    client.force_login(owner)
    query = {'q': 'Synthetic group', 'state': 'provisioning', 'attention': '1'}
    first = client.get(reverse('tenant-console'), query)
    assert len(first.context['tenants']) == 25
    assert 'page=2&amp;q=Synthetic%20group&amp;state=provisioning&amp;attention=1' in first.content.decode()
    last = client.get(reverse('tenant-console'), {**query, 'page': '2'})
    assert len(last.context['tenants']) == 1
    assert last.context['tenants'].number == 2


def test_support_queue_filters_unresolved_priority_owner_and_tenant(client, owner, tenant):
    other_owner = User.objects.create_user('queue-owner', is_superuser=True)
    other_tenant = control.create(owner, **configuration(2, name='Synthetic second business'))
    mine = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data(title='Needle incident', priority='urgent', assignee=owner))
    theirs = portal.create_case(owner, other_tenant.pk, uuid.uuid4(), **case_data(assignee=other_owner))
    resolved = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data(title='Resolved synthetic case'))
    TenantSupportCase.objects.filter(pk=resolved.pk).update(status='resolved', resolution='Synthetic resolved fixture', resolved_at=timezone.now())
    client.force_login(owner)
    url = reverse('tenant-support-queue')
    default = client.get(url)
    assert default.status_code == 200 and 'no-store' in default['Cache-Control']
    assert {case.pk for case in default.context['cases']} == {mine.pk, theirs.pk}
    combinations = [
        ({'assigned': 'me'}, {mine.pk}),
        ({'priority': 'urgent'}, {mine.pk}),
        ({'status': 'resolved'}, {resolved.pk}),
        ({'status': 'all', 'tenant': tenant.pk}, {mine.pk, resolved.pk}),
        ({'q': 'Needle'}, {mine.pk}),
        ({'q': other_tenant.name}, {theirs.pk}),
        ({'assigned': 'me', 'tenant': other_tenant.pk}, set()),
    ]
    for query, expected in combinations:
        response = client.get(url, query)
        assert {case.pk for case in response.context['cases']} == expected
    assert f'href="{case_url(tenant, mine)}"' in default.content.decode()
    assert f'href="{case_url(other_tenant, theirs)}"' in default.content.decode()
    assert client.post(url, {'action': 'update_case'}).status_code == 405


def test_owner_navigation_excludes_clinical_workspace_without_changing_tenant_navigation(client, owner, tenant):
    client.force_login(owner)
    for url in (reverse('tenant-console'), reverse('tenant-support-queue'), detail_url(tenant)):
        response = client.get(url)
        assert response.context['owner_portal'] is True
        assert response.context['show_global_search'] is False
        html = response.content.decode()
        assert 'global-patient-search' not in html
        for clinical in ('/patients', '/suite/find-patient/', '/inventory/stock', '/pharmacy', '/suite/'):
            assert f'href="{clinical}"' not in html
        assert f'href="{reverse("tenant-support-queue")}"' in html
    with override_settings(OWNER_CONTROL_PLANE=False, TENANT_KEY=str(tenant.key)), patch.object(
        tenant_runtime, 'policy_active', return_value=True,
    ):
        response = client.get('/accounts/control/')
        assert response.status_code == 200
        assert response.context['show_global_search'] is True
        assert 'global-patient-search' in response.content.decode()


def test_metadata_exact_replay_and_conflicts_preserve_one_activity(owner, tenant):
    request_id = uuid.uuid4()
    revision = tenant.revision
    changed = portal.update_metadata(owner, tenant.pk, revision, request_id, **metadata())
    replayed = portal.update_metadata(owner, tenant.pk, revision, request_id, **metadata())
    assert changed.revision == replayed.revision == revision + 1
    assert TenantActivity.objects.filter(request_id=request_id).count() == 1
    assert changed.contact_email == 'operations@example.test'
    assert changed.state == 'provisioning' and changed.last_seen_at is None
    for actor, pk, data in (
        (owner, tenant.pk, metadata(contact_name='Changed payload')),
        (User.objects.create_user('second-owner', is_superuser=True), tenant.pk, metadata()),
        (owner, control.create(owner, **configuration(2)).pk, metadata()),
    ):
        with pytest.raises(ValidationError):
            portal.update_metadata(actor, pk, revision, request_id, **data)
    with pytest.raises(ValidationError):
        portal.update_metadata(owner, tenant.pk, revision, uuid.uuid4(), **metadata())
    tenant.refresh_from_db()
    assert tenant.contact_name == metadata()['contact_name']
    assert tenant.revision == revision + 1


@pytest.mark.parametrize('invalid', [
    {'contact_email': 'invalid-email'}, {'contact_phone': 'x' * 41},
    {'operator_notes': 'x' * 2001}, {'contact_name': 'x' * 161},
])
def test_metadata_validation_is_atomic(owner, tenant, invalid):
    before = tenant.activities.count()
    with pytest.raises(ValidationError):
        portal.update_metadata(owner, tenant.pk, tenant.revision, uuid.uuid4(), **metadata(**invalid))
    tenant.refresh_from_db()
    assert tenant.revision == 1 and not tenant.contact_name
    assert tenant.activities.count() == before


def test_metadata_rejects_unknown_fields_partial_updates_and_bad_request_id(owner, tenant):
    for data in ({'contact_name': 'Incomplete'}, {**metadata(), 'state': 'active'}):
        with pytest.raises(ValidationError):
            portal.update_metadata(owner, tenant.pk, tenant.revision, uuid.uuid4(), **data)
    with pytest.raises(ValidationError):
        portal.update_metadata(owner, tenant.pk, tenant.revision, 'not-a-uuid', **metadata())


def test_configuration_before_bundle_preserves_keys_and_blocks_stale_writes(owner, tenant):
    original_keys = control.secrets_for(tenant)
    request_id = uuid.uuid4()
    data = configuration(name='Updated synthetic business', service_type='clinic', services=PRESETS['clinic'])
    changed = portal.configure(owner, tenant.pk, 1, request_id, **data)
    assert changed.revision == 2 and changed.name == data['name']
    assert control.secrets_for(changed) == original_keys
    assert portal.configure(owner, tenant.pk, 1, request_id, **data).revision == 2
    with pytest.raises(ValidationError):
        portal.configure(owner, tenant.pk, 1, uuid.uuid4(), **data)
    assert tenant.activities.filter(event='tenant_configuration_updated').count() == 1


@pytest.mark.parametrize('invalid', [
    {'origin': 'https://owner.example.test'}, {'origin': 'http://unsafe.example.test'},
    {'origin': 'https://tenant.example.test/path'}, {'bind_port': 80},
    {'service_type': 'invented'}, {'services': ['pharmacy']},
    {'services': ['invented']}, {'admin_username': 'invalid username'},
])
def test_configuration_rejects_invalid_setup_without_mutation(owner, tenant, invalid):
    with pytest.raises(ValidationError):
        portal.configure(owner, tenant.pk, tenant.revision, uuid.uuid4(), **configuration(**invalid))
    tenant.refresh_from_db()
    assert tenant.revision == 1 and tenant.origin == configuration()['origin']


def test_first_bundle_locks_configuration_without_rotating_secrets(owner, tenant):
    secrets = control.secrets_for(tenant)
    first = zipfile.ZipFile(io.BytesIO(control.bundle(owner, tenant)))
    checklist = first.read('SETUP_CHECKLIST.txt').decode()
    assert tenant.name in checklist and tenant.origin in checklist
    assert f'{tenant.origin}/accounts/setup/' in checklist
    assert 'Temporary owner support cannot grant permanent access' in checklist
    assert all(secret not in checklist for secret in secrets.values())
    tenant.refresh_from_db()
    generated_at, revision = tenant.bundle_generated_at, tenant.revision
    assert generated_at is not None and revision == 2
    second = zipfile.ZipFile(io.BytesIO(control.bundle(owner, tenant)))
    tenant.refresh_from_db()
    assert first.read('.env') == second.read('.env')
    assert control.secrets_for(tenant) == secrets
    assert (tenant.bundle_generated_at, tenant.revision) == (generated_at, revision)
    with pytest.raises(ValidationError):
        portal.configure(owner, tenant.pk, revision, uuid.uuid4(), **configuration(name='Blocked edit'))
    assert not tenant.last_seen_at and tenant.state == 'provisioning'


def test_upgrade_backfill_locks_legacy_configuration_without_inventing_download(client, owner, tenant):
    downloaded = control.create(owner, **configuration(2))
    actual_download = timezone.now() - timedelta(hours=1)
    TenantDeployment.objects.filter(pk=downloaded.pk).update(bundle_generated_at=actual_download)
    migration = importlib.import_module('apps.accounts.migrations.0013_tenant_admin_portal')
    migration.lock_existing_deployments(apps, SimpleNamespace(connection=connection))
    tenant.refresh_from_db()
    downloaded.refresh_from_db()
    assert tenant.legacy_configuration_locked is True
    assert tenant.bundle_generated_at is None
    assert tenant.configuration_editable is False
    assert downloaded.bundle_generated_at == actual_download
    assert downloaded.legacy_configuration_locked is False
    assert tenant.revision == 1
    assert not tenant.activities.filter(event='tenant_bundle_downloaded').exists()
    with pytest.raises(ValidationError):
        portal.configure(owner, tenant.pk, tenant.revision, uuid.uuid4(), **configuration())
    client.force_login(owner)
    response = client.get(detail_url(tenant))
    assert response.status_code == 200
    assert response.context['configuration_form'] is None
    assert b'predates portal download tracking' in response.content
    fresh = control.create(owner, **configuration(3))
    assert fresh.bundle_generated_at is None and not fresh.legacy_configuration_locked
    assert fresh.configuration_editable is True
    assert portal.configure(owner, fresh.pk, fresh.revision, uuid.uuid4(), **configuration(3, name='Fresh editable setup')).name == 'Fresh editable setup'


def test_heartbeat_locks_setup_and_records_one_activation_without_attesting_readiness(client, owner, tenant):
    for _ in range(2):
        response = client.get(reverse('tenant-policy'), {'ticket': policy_ticket(tenant)})
        assert response.status_code == 200
    tenant.refresh_from_db()
    assert tenant.state == 'active' and tenant.last_seen_at
    assert not tenant.readiness_checks.exists()
    assert tenant.activities.filter(event='tenant_first_contact').count() == 1
    with pytest.raises(ValidationError):
        portal.configure(owner, tenant.pk, tenant.revision, uuid.uuid4(), **configuration())


def test_readiness_is_attributed_attestation_and_never_activates_tenant(client, owner, tenant):
    for step, _ in CHECKPOINTS:
        request_id = uuid.uuid4()
        revision = tenant.revision
        tenant = portal.readiness(owner, tenant.pk, revision, request_id, step, 'verified', ' Synthetic operator evidence. ')
        assert portal.readiness(owner, tenant.pk, revision, request_id, step, 'verified', 'Synthetic operator evidence.').revision == tenant.revision
    assert tenant.readiness_checks.count() == len(CHECKPOINTS)
    assert tenant.state == 'provisioning' and tenant.last_seen_at is None
    assert tenant.readiness_checks.filter(updated_by=owner, evidence='Synthetic operator evidence.').count() == len(CHECKPOINTS)
    assert tenant.activities.filter(event='tenant_readiness_updated').count() == len(CHECKPOINTS)
    client.force_login(owner)
    page = client.get(detail_url(tenant))
    assert page.context['readiness_done'] == page.context['readiness_total'] == len(CHECKPOINTS)
    tenant = portal.readiness(owner, tenant.pk, tenant.revision, uuid.uuid4(), 'recovery', 'pending', 'Restore evidence needs review.')
    assert tenant.readiness_checks.count() == len(CHECKPOINTS)
    assert tenant.readiness_checks.get(step='recovery').status == 'pending'


@pytest.mark.parametrize('step,status,evidence', [
    ('invented', 'verified', 'Evidence'), ('isolation', 'invented', 'Evidence'),
    ('isolation', 'verified', ' '), ('isolation', 'pending', ''),
    ('isolation', 'verified', 'x' * 501),
])
def test_readiness_rejects_invalid_attestation(owner, tenant, step, status, evidence):
    with pytest.raises(ValidationError):
        portal.readiness(owner, tenant.pk, tenant.revision, uuid.uuid4(), step, status, evidence)
    tenant.refresh_from_db()
    assert tenant.revision == 1 and not tenant.readiness_checks.exists()


def test_case_creation_exact_replay_does_not_create_access_or_duplicate_activity(owner, tenant):
    request_id = uuid.uuid4()
    before_users = User.objects.count()
    case = portal.create_case(owner, tenant.pk, request_id, **case_data(assignee=owner))
    repeated = portal.create_case(owner, tenant.pk, request_id, **case_data(assignee=owner))
    assert repeated.pk == case.pk and case.revision == 1
    assert TenantSupportCase.objects.count() == case.activities.count() == 1
    assert case.created_by == owner and case.assignee == owner
    assert User.objects.count() == before_users and not OwnerSupportReceipt.objects.exists()
    with pytest.raises(ValidationError):
        portal.create_case(owner, tenant.pk, request_id, **case_data(title='Conflicting retry', assignee=owner))


@pytest.mark.parametrize('kind', ['staff', 'inactive_owner', 'temporary_support'])
def test_case_assignee_must_be_active_permanent_owner(owner, tenant, kind):
    candidate = User.objects.create_user(
        f'assignee-{kind}', role='admin', is_superuser=kind != 'staff',
        is_active=kind != 'inactive_owner',
    )
    if kind == 'temporary_support':
        OwnerSupportReceipt.objects.create(
            nonce=uuid.uuid4(), user=candidate, owner_reference=str(owner.pk),
            reason='Synthetic', expires_at=timezone.now() + timedelta(minutes=30),
        )
    with pytest.raises(ValidationError):
        portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data(assignee=candidate))
    assert not TenantSupportCase.objects.exists()
    assert not CaseForm().fields['assignee'].queryset.filter(pk=candidate.pk).exists()


def test_case_requires_assignment_resolution_and_explicit_reopening(owner, tenant):
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data())
    with pytest.raises(ValidationError):
        portal.update_case(owner, tenant.pk, case.pk, 1, uuid.uuid4(), **case_update(status='in_progress'))
    case = portal.update_case(owner, tenant.pk, case.pk, 1, uuid.uuid4(), **case_update(status='in_progress', assignee=owner, priority='high'))
    assert case.assignee == owner and case.status == 'in_progress' and case.priority == 'high'
    with pytest.raises(ValidationError):
        portal.update_case(owner, tenant.pk, case.pk, case.revision, uuid.uuid4(), **case_update(status='resolved'))
    case = portal.update_case(owner, tenant.pk, case.pk, case.revision, uuid.uuid4(), **case_update(status='waiting', assignee=owner))
    case = portal.update_case(owner, tenant.pk, case.pk, case.revision, uuid.uuid4(), **case_update(status='resolved', assignee=owner, resolution='Synthetic setup verified.'))
    assert case.resolved_at is not None and case.resolution == 'Synthetic setup verified.'
    with pytest.raises(ValidationError):
        portal.update_case(owner, tenant.pk, case.pk, case.revision, uuid.uuid4(), **case_update(status='in_progress', assignee=owner))
    case = portal.update_case(owner, tenant.pk, case.pk, case.revision, uuid.uuid4(), **case_update(status='open', assignee=owner, note='Synthetic issue recurred.'))
    assert case.status == 'open' and case.resolved_at is None
    assert case.activities.count() == 5


def test_case_update_retry_stale_revision_and_invalid_fields_are_atomic(owner, tenant):
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data())
    request_id = uuid.uuid4()
    data = case_update(status='in_progress', assignee=owner)
    updated = portal.update_case(owner, tenant.pk, case.pk, 1, request_id, **data)
    repeated = portal.update_case(owner, tenant.pk, case.pk, 1, request_id, **data)
    assert updated.revision == repeated.revision == 2
    assert case.activities.count() == 2
    with pytest.raises(ValidationError):
        portal.update_case(owner, tenant.pk, case.pk, 1, uuid.uuid4(), **data)
    for invalid in ({'note': ''}, {'note': 'x' * 501}, {'status': 'invented'}, {'priority': 'invented'}):
        with pytest.raises(ValidationError):
            portal.update_case(owner, tenant.pk, case.pk, 2, uuid.uuid4(), **{**data, **invalid})
    case.refresh_from_db()
    assert case.revision == 2 and case.status == 'in_progress'
    assert case.activities.count() == 2


def test_case_routes_and_service_enforce_tenant_binding(client, owner, tenant):
    other = control.create(owner, **configuration(2))
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data())
    client.force_login(owner)
    assert client.get(detail_url(tenant)).status_code == 200
    assert client.get(case_url(tenant, case)).status_code == 200
    assert client.get(case_url(other, case)).status_code == 404
    payload = {'action': 'update_case', 'request_id': uuid.uuid4(), 'revision': 1, **case_update()}
    payload['assignee'] = ''
    assert client.post(case_url(other, case), payload).status_code == 404
    with pytest.raises(TenantSupportCase.DoesNotExist):
        portal.update_case(owner, other.pk, case.pk, 1, uuid.uuid4(), **case_update())
    assert not other.activities.filter(case=case).exists()
    assert case.activities.count() == 1


def test_activity_history_pagination_keeps_old_tenant_and_case_events_accessible(client, owner, tenant):
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data())
    TenantActivity.objects.bulk_create([
        TenantActivity(tenant=tenant, case=case, actor=owner, event='tenant_case_updated', summary=f'Synthetic update {index:02d}')
        for index in range(26)
    ])
    client.force_login(owner)
    for url, key, total, anchor in (
        (detail_url(tenant), 'events', 28, 'activity'),
        (case_url(tenant, case), 'updates', 27, 'updates-title'),
    ):
        first = client.get(url)
        first_ids = {event.pk for event in first.context[key]}
        assert len(first_ids) == 25
        assert first.context[key].paginator.count == total
        assert f'?activity_page=2#{anchor}' in first.content.decode()
        if key == 'events':
            assert b'Support case updated' in first.content
        older = client.get(url, {'activity_page': '2'})
        older_ids = {event.pk for event in older.context[key]}
        assert older.context[key].number == 2
        assert len(older_ids) == total - 25 and not first_ids & older_ids
        assert len(first_ids | older_ids) == total
        assert f'?activity_page=1#{anchor}' in older.content.decode()


def test_retirement_requires_suspension_is_terminal_and_retains_records(client, owner, tenant):
    TenantDeployment.objects.filter(pk=tenant.pk).update(state='active', last_seen_at=timezone.now())
    tenant.refresh_from_db()
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data())
    with pytest.raises(ValidationError):
        control.state(owner, tenant.pk, 'retired', tenant.revision, 'Synthetic handover')
    suspended = control.state(owner, tenant.pk, 'suspended', tenant.revision, 'Synthetic maintenance')
    assert control.support_ticket(owner, suspended, 'Synthetic authorized diagnostic work')
    request_id = uuid.uuid4()
    retired = control.state(owner, tenant.pk, 'retired', suspended.revision, 'Synthetic retention plan', request_id)
    assert control.state(owner, tenant.pk, 'retired', suspended.revision, 'Synthetic retention plan', request_id).revision == retired.revision
    for decision in ('active', 'suspended', 'retired'):
        with pytest.raises(ValidationError):
            control.state(owner, tenant.pk, decision, retired.revision, 'Synthetic change', uuid.uuid4())
    # Stale objects cannot bypass the newly stored retired state.
    with pytest.raises(ValidationError):
        control.bundle(owner, suspended)
    with pytest.raises(ValidationError):
        control.support_ticket(owner, suspended, 'Blocked access')
    with pytest.raises(ValidationError):
        portal.readiness(owner, tenant.pk, retired.revision, uuid.uuid4(), 'isolation', 'verified', 'Synthetic evidence')
    response = client.get(reverse('tenant-policy'), {'ticket': policy_ticket(retired)})
    assert response.status_code == 200
    policy = signing.loads(response.content.decode(), key=control.secrets_for(retired)['support'], salt='tenant-policy-response', fallback_keys=[])
    assert policy['active'] is False
    retired.refresh_from_db()
    assert retired.state == 'retired' and retired.revision == suspended.revision + 1
    assert TenantDeployment.objects.filter(pk=tenant.pk).exists()
    assert TenantSupportCase.objects.filter(pk=case.pk).exists()
    assert TenantActivity.objects.filter(request_id=request_id).count() == 1


def test_forms_reject_missing_replay_id_and_stale_revision(client, owner, tenant):
    client.force_login(owner)
    data = {'action': 'metadata', 'revision': tenant.revision, **metadata()}
    response = client.post(detail_url(tenant), data)
    assert response.status_code == 200 and response.context['metadata_form'].errors
    data['request_id'] = str(uuid.uuid4())
    assert client.post(detail_url(tenant), data).status_code == 302
    assert client.post(detail_url(tenant), data).status_code == 302
    data['request_id'] = str(uuid.uuid4())
    response = client.post(detail_url(tenant), data)
    assert response.status_code == 200 and response.context['metadata_form'].non_field_errors()
    tenant.refresh_from_db()
    assert tenant.revision == 2


def test_case_form_creation_update_and_validation(client, owner, tenant):
    client.force_login(owner)
    create_data = {'action': 'create_case', 'request_id': str(uuid.uuid4()), 'assignee': owner.pk, **case_data()}
    response = client.post(detail_url(tenant), create_data)
    case = TenantSupportCase.objects.get()
    assert response.status_code == 302 and response.url == case_url(tenant, case)
    assert client.post(detail_url(tenant), create_data).url == response.url
    update = {'action': 'update_case', 'request_id': str(uuid.uuid4()), 'revision': case.revision, **case_update(status='resolved', assignee=owner.pk)}
    invalid = client.post(case_url(tenant, case), update)
    assert invalid.status_code == 200 and invalid.context['update_form'].non_field_errors()
    update['resolution'] = 'Synthetic operator resolution.'
    assert client.post(case_url(tenant, case), update).status_code == 302
    assert client.post(case_url(tenant, case), update).status_code == 302
    case.refresh_from_db()
    assert case.status == 'resolved' and case.revision == 2


def test_get_requests_never_mutate_portal_and_posts_require_csrf(owner, tenant):
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data())
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(owner)
    before = (tenant.revision, TenantActivity.objects.count(), TenantSupportCase.objects.count())
    for url in (reverse('tenant-console'), detail_url(tenant), case_url(tenant, case)):
        assert strict.get(url, {'action': 'retired', 'revision': 1}).status_code == 200
        assert strict.post(url, {'action': 'retired', 'revision': 1}).status_code == 403
        assert strict.put(url, HTTP_X_CSRFTOKEN=strict.cookies['csrftoken'].value).status_code == 405
    action_url = reverse('tenant-action', args=[tenant.pk])
    assert strict.get(action_url, {'action': 'bundle'}).status_code == 405
    assert strict.post(action_url, {'action': 'bundle'}).status_code == 403
    tenant.refresh_from_db()
    assert (tenant.revision, TenantActivity.objects.count(), TenantSupportCase.objects.count()) == before
    assert tenant.bundle_generated_at is None and tenant.state == 'provisioning'


def test_portal_pages_are_private_escape_notes_and_never_render_stored_secrets(client, owner, tenant):
    tenant = portal.update_metadata(owner, tenant.pk, tenant.revision, uuid.uuid4(), **metadata(operator_notes='<script>alert("synthetic")</script>'))
    case = portal.create_case(owner, tenant.pk, uuid.uuid4(), **case_data(detail='<script>synthetic()</script>'))
    client.force_login(owner)
    secrets = [tenant.secret_envelope, *control.secrets_for(tenant).values()]
    for url in (reverse('tenant-console'), reverse('tenant-support-queue'), detail_url(tenant), case_url(tenant, case)):
        response = client.get(url)
        assert response.status_code == 200
        assert 'no-store' in response['Cache-Control']
        html = response.content.decode()
        assert all(secret not in html for secret in secrets)
        assert '<script>alert(' not in html and '<script>synthetic()' not in html
    assert '&lt;script&gt;' in client.get(detail_url(tenant)).content.decode()
    assert '&lt;script&gt;' in client.get(case_url(tenant, case)).content.decode()


def _concurrent_calls(operation):
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                result = operation()
                return ('saved', result.pk)
            except ValidationError:
                return ('rejected', None)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        return [future.result(timeout=30) for future in futures]


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_metadata_edits_cannot_overwrite_same_revision(owner, tenant):
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks; SQLite is not a locking proof.')
    outcomes = _concurrent_calls(lambda: portal.update_metadata(
        User.objects.get(pk=owner.pk), tenant.pk, 1, uuid.uuid4(), **metadata(),
    ))
    assert sorted(result[0] for result in outcomes) == ['rejected', 'saved']
    tenant.refresh_from_db()
    assert tenant.revision == 2
    assert tenant.activities.filter(event='tenant_metadata_updated').count() == 1


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_case_retry_creates_one_case_and_activity(owner, tenant):
    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks; SQLite is not a locking proof.')
    request_id = uuid.uuid4()
    outcomes = _concurrent_calls(lambda: portal.create_case(
        User.objects.get(pk=owner.pk), tenant.pk, request_id, **case_data(),
    ))
    assert [result[0] for result in outcomes] == ['saved', 'saved']
    assert outcomes[0][1] == outcomes[1][1]
    assert TenantSupportCase.objects.count() == 1
    assert TenantActivity.objects.filter(request_id=request_id).count() == 1
