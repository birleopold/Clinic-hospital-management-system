"""Administrative UI over control-plane records, never tenant clinical databases."""
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from common.service_policy import PRESETS, SERVICES
from .models import TenantDeployment, TenantSupportCase
from .tenant_portal_models import CHECKPOINTS
from . import tenant_services, tenant_portal_services as service
from .tenant_portal_forms import WorkspaceForm, MetadataForm, ConfigurationForm, ReadinessForm, LifecycleForm, SupportLaunchForm, CaseForm, CaseUpdateForm

CHECK_HELP = {
    'isolation': 'Confirm this business has its own application process, database, private media, keys and Redis. Branch facilities share only this business.',
    'https': 'Confirm the tenant hostname uses trusted HTTPS, the proxy strips forwarded headers, and database, Redis and media are not publicly exposed.',
    'recovery': 'Record a separate database/media backup and a successful isolated restore rehearsal with an operator evidence reference.',
    'administrator': 'Have the tenant administrator change the bootstrap password, enroll MFA and review recovery procedures through the tenant application.',
    'services': 'Review enabled services, branding, rooms, departments, catalogues and applicable local policies with the tenant administrator.',
    'staff': 'The permanent tenant administrator recruits staff and assigns roles. Test each role from the actual browser workstation; no remote device management is provided.',
    'acceptance': 'Record tenant sign-off on representative daily workflows, training and clinical/provider commissioning where required.',
}


def _error(form, exc):
    form.add_error(None, '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'This tenant origin or private port is already registered. Reload and choose an unused value.')


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def console(request):
    tenant_services.owner(request.user)
    preset = request.GET.get('preset', 'clinic')
    if preset not in PRESETS:preset = 'clinic'
    form = WorkspaceForm(request.POST or None, initial={'service_type': preset, 'services': PRESETS[preset]}, auto_id='register_%s')
    if request.method == 'POST' and form.is_valid():
        try:tenant = tenant_services.create(request.user, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:_error(form, exc)
        else:
            messages.success(request, 'Tenant registered. Complete its isolated deployment and workspace setup next.')
            return redirect('tenant-detail', pk=tenant.pk)
    all_rows = TenantDeployment.objects.all()
    rows = all_rows.defer('secret_envelope').annotate(open_cases=Count('support_cases', filter=~Q(support_cases__status='resolved'), distinct=True), ready_count=Count('readiness_checks', filter=Q(readiness_checks__status='verified'), distinct=True))
    q = request.GET.get('q', '').strip()[:160]
    state = request.GET.get('state', '')
    attention = request.GET.get('attention') == '1'
    if q:rows = rows.filter(Q(name__icontains=q) | Q(origin__icontains=q) | Q(contact_name__icontains=q) | Q(contact_email__icontains=q) | Q(deployment_label__icontains=q))
    if state in dict(TenantDeployment._meta.get_field('state').choices):rows = rows.filter(state=state)
    else:state = ''
    if attention:
        rows = rows.exclude(state='retired').filter(Q(last_seen_at__isnull=True) | Q(last_seen_at__lt=timezone.now()-timedelta(minutes=10)) | Q(ready_count__lt=len(CHECKPOINTS)) | Q(open_cases__gt=0))
    stats = {'total': all_rows.count(), 'open_cases': TenantSupportCase.objects.exclude(status='resolved').count()}
    stats.update({key: all_rows.filter(state=key).count() for key, _ in TenantDeployment._meta.get_field('state').choices})
    return render(request, 'accounts/tenants.html', {'form': form, 'tenants': Paginator(rows.order_by('name', 'pk'), 25).get_page(request.GET.get('page')), 'stats': stats, 'q': q, 'state': state, 'attention': attention, 'readiness_total': len(CHECKPOINTS), 'presets': PRESETS})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    tenant_services.owner(request.user)
    tenant = get_object_or_404(TenantDeployment.objects.defer('secret_envelope'), pk=pk)
    action = request.POST.get('action') if request.method == 'POST' else None
    initial = {'revision': tenant.revision}
    metadata_form = MetadataForm(request.POST if action == 'metadata' else None, initial={**initial, 'action': 'metadata', **{key: getattr(tenant, key) for key in ('contact_name', 'contact_email', 'contact_phone', 'deployment_label', 'operator_notes')}}, auto_id='metadata_%s')
    configuration_form = None
    if action == 'configure' or tenant.configuration_editable:
        configuration_form = ConfigurationForm(request.POST if action == 'configure' else None, initial={**initial, 'action': 'configure', **{key: getattr(tenant, key) for key in ('name', 'origin', 'bind_port', 'admin_username', 'service_type', 'services')}}, auto_id='configuration_%s')
    lifecycle_form = LifecycleForm(request.POST if action in ('active', 'suspended', 'retired') else None, initial=initial, auto_id='lifecycle_%s')
    support_launch_form = SupportLaunchForm(request.POST if action == 'support' else None, auto_id='launch_%s')
    support_form = CaseForm(request.POST if action == 'create_case' else None, initial={'action': 'create_case'}, auto_id='case_%s')
    existing = {row.step: row for row in tenant.readiness_checks.select_related('updated_by')}
    checkpoints = []
    selected_form = None
    for key, label in CHECKPOINTS:
        row = existing.get(key)
        bound = action == 'readiness' and request.POST.get('step') == key
        form = ReadinessForm(request.POST if bound else None, initial={**initial, 'action': 'readiness', 'step': key, 'status': row.status if row else 'pending', 'evidence': row.evidence if row else ''}, auto_id=f'check_{key}_%s')
        if bound:selected_form = form
        checkpoints.append({'key': key, 'label': label, 'description': CHECK_HELP[key], 'status': row.status if row else 'pending', 'evidence': row.evidence if row else '', 'updated_at': row.updated_at if row else None, 'updated_by': row.updated_by if row else None, 'form': form})
    forms = {'metadata': metadata_form, 'configure': configuration_form, 'readiness': selected_form, 'create_case': support_form, 'support': support_launch_form, 'active': lifecycle_form, 'suspended': lifecycle_form, 'retired': lifecycle_form}
    if request.method == 'POST':
        form = forms.get(action)
        if form is None:messages.error(request, 'Choose a valid portal action and reload its form.')
        elif form.is_valid():
            data = dict(form.cleaned_data);data.pop('action', None)
            try:
                if action == 'metadata':service.update_metadata(request.user, pk, **data)
                elif action == 'configure':service.configure(request.user, pk, **data)
                elif action == 'readiness':service.readiness(request.user, pk, **data)
                elif action == 'create_case':
                    case = service.create_case(request.user, pk, **data)
                    return redirect('tenant-support-case', tenant_pk=pk, pk=case.pk)
                elif action == 'support':
                    ticket = tenant_services.support_ticket(request.user, tenant, data['reason'])
                    response = render(request, 'accounts/support_launch.html', {'origin': tenant.origin, 'ticket': ticket, 'tenant': tenant})
                    response['Referrer-Policy'] = 'no-referrer'
                    return response
                else:tenant_services.state(request.user, pk, action, **data)
            except (ValidationError, IntegrityError) as exc:_error(form, exc)
            else:
                messages.success(request, 'Tenant record updated.')
                return redirect('tenant-detail', pk=pk)
    return render(request, 'accounts/tenant_detail.html', {'tenant': tenant, 'metadata_form': metadata_form, 'configuration_form': configuration_form, 'checkpoints': checkpoints, 'support_form': support_form, 'support_launch_form': support_launch_form, 'lifecycle_form': lifecycle_form, 'cases': tenant.support_cases.select_related('assignee').order_by('-updated_at', '-pk')[:50], 'events': Paginator(tenant.activities.select_related('actor').all(), 25).get_page(request.GET.get('activity_page')), 'service_labels': [SERVICES[key][0] for key in tenant.services if key in SERVICES], 'health_label': tenant.health_label, 'readiness_done': sum(row.status == 'verified' for row in existing.values()), 'readiness_total': len(CHECKPOINTS)})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def support_case(request, tenant_pk, pk):
    tenant_services.owner(request.user)
    tenant = get_object_or_404(TenantDeployment.objects.defer('secret_envelope'), pk=tenant_pk)
    case = get_object_or_404(TenantSupportCase.objects.select_related('assignee', 'created_by'), tenant=tenant, pk=pk)
    form = CaseUpdateForm(request.POST or None, initial={'action': 'update_case', 'revision': case.revision, 'status': case.status, 'priority': case.priority, 'assignee': case.assignee, 'resolution': case.resolution}, auto_id='case_update_%s')
    if request.method == 'POST' and form.is_valid():
        data = dict(form.cleaned_data);data.pop('action')
        try:service.update_case(request.user, tenant_pk, pk, **data)
        except ValidationError as exc:_error(form, exc)
        else:
            messages.success(request, 'Support case updated.')
            return redirect('tenant-support-case', tenant_pk=tenant_pk, pk=pk)
    return render(request, 'accounts/tenant_support_case.html', {'tenant': tenant, 'case': case, 'update_form': form, 'updates': Paginator(case.activities.select_related('actor').all(), 25).get_page(request.GET.get('activity_page'))})


@login_required
@never_cache
@require_http_methods(['GET'])
def support_queue(request):
    tenant_services.owner(request.user)
    rows = TenantSupportCase.objects.select_related('tenant', 'assignee')
    q = request.GET.get('q', '').strip()[:160]
    status = request.GET.get('status', 'unresolved')
    priority = request.GET.get('priority', '')
    assigned = 'me' if request.GET.get('assigned') == 'me' else ''
    status_options = TenantSupportCase._meta.get_field('status').choices
    priority_options = TenantSupportCase._meta.get_field('priority').choices
    if q:rows = rows.filter(Q(title__icontains=q) | Q(tenant__name__icontains=q))
    if status == 'unresolved':rows = rows.exclude(status='resolved')
    elif status in dict(status_options):rows = rows.filter(status=status)
    else:status = 'all'
    if priority in dict(priority_options):rows = rows.filter(priority=priority)
    else:priority = ''
    if assigned:rows = rows.filter(assignee=request.user)
    tenant_filter = request.GET.get('tenant', '')
    if tenant_filter.isdigit():rows = rows.filter(tenant_id=tenant_filter)
    else:tenant_filter = ''
    return render(request, 'accounts/tenant_support_queue.html', {'cases': Paginator(rows.order_by('-updated_at', '-pk'), 25).get_page(request.GET.get('page')), 'q': q, 'status': status, 'priority': priority, 'assigned': assigned, 'status_options': status_options, 'priority_options': priority_options, 'tenant_filter': tenant_filter})
