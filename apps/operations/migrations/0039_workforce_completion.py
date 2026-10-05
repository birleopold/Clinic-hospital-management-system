"""Audited employment, credential renewals, roster coverage and attendance policy."""
import importlib
import simple_history.models
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q, F

canonical = importlib.import_module('apps.operations.migrations.0015_canonical_patient_guards')


def remove_guards(apps, schema_editor):
    canonical.uninstall(apps, schema_editor)


def install_guards(apps, schema_editor):
    canonical.uninstall(apps, schema_editor)
    canonical.install(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ('operations', '0038_historicalrefundauthorization_authorized_amount_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.RunPython(remove_guards, install_guards),
        migrations.CreateModel(
            name='StaffEmployment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('facility', models.ForeignKey(on_delete=models.PROTECT, to='accounts.facility')),
                ('staff', models.ForeignKey(on_delete=models.PROTECT, related_name='employment_records', to=settings.AUTH_USER_MODEL)),
                ('employment_type', models.CharField(max_length=16, choices=[('permanent', 'Permanent'), ('fixed_term', 'Fixed term'), ('locum', 'Locum'), ('volunteer', 'Volunteer')])),
                ('status', models.CharField(max_length=16, choices=[('onboarding', 'Onboarding'), ('active', 'Active'), ('suspended', 'Suspended'), ('ended', 'Ended')], default='onboarding')),
                ('starts_on', models.DateField()),
                ('ends_on', models.DateField(null=True, blank=True, help_text='Last eligible employment date, inclusive.')),
                ('reason', models.CharField(max_length=250)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('created_by', models.ForeignKey(on_delete=models.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=['facility', 'staff'], name='unique_facility_employment'), models.CheckConstraint(condition=Q(ends_on__isnull=True) | Q(ends_on__gte=F('starts_on')), name='employment_date_order'), models.CheckConstraint(condition=~Q(status='ended') | Q(ends_on__isnull=False), name='ended_employment_has_date')]},
        ),
        migrations.CreateModel(
            name='HistoricalStaffEmployment',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('created_at', models.DateTimeField(blank=True, editable=False)),
                ('facility', models.ForeignKey(to='accounts.facility', blank=True, null=True, db_constraint=False, on_delete=models.DO_NOTHING, related_name='+')),
                ('staff', models.ForeignKey(to=settings.AUTH_USER_MODEL, blank=True, null=True, db_constraint=False, on_delete=models.DO_NOTHING, related_name='+')),
                ('employment_type', models.CharField(max_length=16, choices=[('permanent', 'Permanent'), ('fixed_term', 'Fixed term'), ('locum', 'Locum'), ('volunteer', 'Volunteer')])),
                ('status', models.CharField(max_length=16, choices=[('onboarding', 'Onboarding'), ('active', 'Active'), ('suspended', 'Suspended'), ('ended', 'Ended')], default='onboarding')),
                ('starts_on', models.DateField()),
                ('ends_on', models.DateField(null=True, blank=True, help_text='Last eligible employment date, inclusive.')),
                ('reason', models.CharField(max_length=250)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('created_by', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=models.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical staff employment',
                'verbose_name_plural': 'historical staff employments',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='DutyCoverageRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('department', models.ForeignKey(on_delete=models.PROTECT, related_name='duty_coverage_rules', to='accounts.department')),
                ('role', models.CharField(max_length=32)),
                ('minimum_staff', models.PositiveSmallIntegerField(default=1)),
                ('include_on_call', models.BooleanField(default=False)),
                ('enabled', models.BooleanField(default=True)),
                ('reason', models.CharField(max_length=250)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('created_by', models.ForeignKey(on_delete=models.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=['department', 'role'], name='unique_department_duty_role'), models.CheckConstraint(condition=Q(minimum_staff__gte=1, minimum_staff__lte=200), name='duty_coverage_valid_minimum')]},
        ),
        migrations.CreateModel(
            name='HistoricalDutyCoverageRule',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('created_at', models.DateTimeField(blank=True, editable=False)),
                ('department', models.ForeignKey(to='accounts.department', blank=True, null=True, db_constraint=False, on_delete=models.DO_NOTHING, related_name='+')),
                ('role', models.CharField(max_length=32)),
                ('minimum_staff', models.PositiveSmallIntegerField(default=1)),
                ('include_on_call', models.BooleanField(default=False)),
                ('enabled', models.BooleanField(default=True)),
                ('reason', models.CharField(max_length=250)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('created_by', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=models.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical duty coverage rule',
                'verbose_name_plural': 'historical duty coverage rules',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name='AttendancePolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('facility', models.ForeignKey(on_delete=models.PROTECT, related_name='attendance_policies', to='accounts.facility')),
                ('effective_from', models.DateField()),
                ('grace_minutes', models.PositiveSmallIntegerField(default=0)),
                ('rounding_minutes', models.PositiveSmallIntegerField(default=0, help_text='0 preserves exact worked minutes.')),
                ('rounding_mode', models.CharField(max_length=12, choices=[('nearest', 'Nearest increment (half up)'), ('down', 'Round down'), ('up', 'Round up')], default='nearest')),
                ('reason', models.CharField(max_length=250)),
                ('created_by', models.ForeignKey(on_delete=models.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=['facility', 'effective_from'], name='unique_attendance_policy_date'), models.CheckConstraint(condition=Q(grace_minutes__lte=120), name='attendance_grace_limit'), models.CheckConstraint(condition=Q(rounding_minutes__in=[0, 1, 5, 10, 15, 30]), name='attendance_rounding_increment')]},
        ),
        migrations.CreateModel(
            name='HistoricalAttendancePolicy',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('created_at', models.DateTimeField(blank=True, editable=False)),
                ('facility', models.ForeignKey(to='accounts.facility', blank=True, null=True, db_constraint=False, on_delete=models.DO_NOTHING, related_name='+')),
                ('effective_from', models.DateField()),
                ('grace_minutes', models.PositiveSmallIntegerField(default=0)),
                ('rounding_minutes', models.PositiveSmallIntegerField(default=0, help_text='0 preserves exact worked minutes.')),
                ('rounding_mode', models.CharField(max_length=12, choices=[('nearest', 'Nearest increment (half up)'), ('down', 'Round down'), ('up', 'Round up')], default='nearest')),
                ('reason', models.CharField(max_length=250)),
                ('created_by', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=models.DO_NOTHING, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=models.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'historical attendance policy',
                'verbose_name_plural': 'historical attendance policys',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.AddField(model_name='staffcredential', name='supersedes', field=models.OneToOneField(null=True, blank=True, on_delete=models.PROTECT, related_name='renewal', to='operations.staffcredential')),
        migrations.AddField(model_name='historicalstaffcredential', name='supersedes', field=models.ForeignKey(to='operations.staffcredential', blank=True, null=True, db_constraint=False, on_delete=models.DO_NOTHING, related_name='+')),
        migrations.AddField(model_name='attendance', name='policy_snapshot', field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name='historicalattendance', name='policy_snapshot', field=models.JSONField(default=dict, blank=True)),
        migrations.RunPython(install_guards, remove_guards),
    ]
