import uuid
import django.db.models.deletion
import django.core.validators
from django.conf import settings
from django.db import migrations, models


def lock_existing_deployments(apps, schema_editor):
    # The previous release did not record downloads. A historical bundle may
    # already exist, so conservatively freeze every pre-upgrade registration.
    Tenant = apps.get_model('accounts', 'TenantDeployment')
    Tenant.objects.using(schema_editor.connection.alias).filter(bundle_generated_at__isnull=True).update(legacy_configuration_locked=True)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0012_workforce_approval_authority')]
    operations = [
        migrations.AlterField(model_name='tenantdeployment', name='state', field=models.CharField(choices=[('provisioning', 'Awaiting deployment'), ('active', 'Active'), ('suspended', 'Suspended'), ('retired', 'Retired')], default='provisioning', max_length=20)),
        migrations.AddField(model_name='tenantdeployment', name='contact_name', field=models.CharField(blank=True, max_length=160)),
        migrations.AddField(model_name='tenantdeployment', name='contact_email', field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name='tenantdeployment', name='contact_phone', field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name='tenantdeployment', name='deployment_label', field=models.CharField(blank=True, max_length=160)),
        migrations.AddField(model_name='tenantdeployment', name='operator_notes', field=models.TextField(blank=True, max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)])),
        migrations.AddField(model_name='tenantdeployment', name='bundle_generated_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='tenantdeployment', name='legacy_configuration_locked', field=models.BooleanField(default=False)),
        migrations.RunPython(lock_existing_deployments, migrations.RunPython.noop),
        migrations.CreateModel(
            name='TenantReadinessCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('step', models.CharField(choices=[('isolation', 'Isolated application and storage'), ('https', 'HTTPS and private network reviewed'), ('recovery', 'Backup and restore rehearsal'), ('administrator', 'Tenant administrator and MFA ready'), ('services', 'Services and branding reviewed'), ('staff', 'Staff roles and workstations checked'), ('acceptance', 'Tenant workflow acceptance recorded')], max_length=24)),
                ('status', models.CharField(choices=[('pending', 'Needs review'), ('verified', 'Operator verified')], default='pending', max_length=16)),
                ('evidence', models.CharField(max_length=500)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='readiness_checks', to='accounts.tenantdeployment')),
                ('updated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('tenant', 'step'), name='tenant_readiness_unique_step')]},
        ),
        migrations.CreateModel(
            name='TenantSupportCase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('title', models.CharField(max_length=160)),
                ('category', models.CharField(choices=[('onboarding', 'Onboarding'), ('access', 'Access'), ('configuration', 'Configuration'), ('incident', 'Incident'), ('other', 'Other')], max_length=24)),
                ('priority', models.CharField(choices=[('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent')], default='normal', max_length=16)),
                ('status', models.CharField(choices=[('open', 'Open'), ('in_progress', 'In progress'), ('waiting', 'Waiting on tenant'), ('resolved', 'Resolved')], default='open', max_length=16)),
                ('detail', models.TextField(max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)])),
                ('resolution', models.TextField(blank=True, max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('assignee', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='support_cases', to='accounts.tenantdeployment')),
            ],
            options={'indexes': [models.Index(fields=['tenant', 'status'], name='tenant_case_status_idx')]},
        ),
        migrations.CreateModel(
            name='TenantActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.CharField(max_length=60)),
                ('summary', models.CharField(max_length=600)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('request_id', models.UUIDField(blank=True, null=True, unique=True)),
                ('request_payload', models.JSONField(default=dict, editable=False)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('case', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='activities', to='accounts.tenantsupportcase')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='activities', to='accounts.tenantdeployment')),
            ],
            options={'ordering': ['-created_at', '-pk']},
        ),
    ]
