import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-secret-key')
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = ['*'] if DEBUG else os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'guardian',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'rest_framework',
    'drf_spectacular',
    'django_filters',
    'simple_history',
    'apps.operations.apps.OperationsConfig',
    'apps.audit.apps.AuditConfig',
    'apps.accounts.apps.AccountsConfig',
    'apps.demographics.apps.DemographicsConfig',
    'apps.appointments.apps.AppointmentsConfig',
    'apps.orders.apps.OrdersConfig',
    'apps.pharmacy.apps.PharmacyConfig',
    'apps.billing.apps.BillingConfig',
    'apps.inventory.apps.InventoryConfig',
    'apps.encounters.apps.EncountersConfig',
    'apps.reports.apps.ReportsConfig',
    'apps.integrations.apps.IntegrationsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'common.workflow_middleware.WorkflowValidationMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'common.tenant_runtime.TenantRuntimeMiddleware',
    'common.access_middleware.AccessSafeguardsMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'common.mfa.MFAGateMiddleware',
    'common.branch_access.BranchScopeMiddleware',
    'common.service_policy.ServiceGateMiddleware',
    'common.visiting_access.VisitingAccessMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
    'apps.audit.middleware.RequestAuditMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'common.workspace_context.workspace_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Kampala'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'common.staticfiles.ContentVersionedStaticFilesStorage'},
}
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/suite/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

AUTH_USER_MODEL = 'accounts.User'

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'common.visiting_access.StaffJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'UG HMS API',
    'VERSION': '0.1.0',
}

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'guardian.backends.ObjectPermissionBackend',
)

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_TASK_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

INTEGRATIONS_SMS_BACKEND = os.getenv(
    'INTEGRATIONS_SMS_BACKEND',
    'apps.integrations.backends.NoOpSmsBackend',
)
INTEGRATIONS_MOMO_BACKEND = os.getenv(
    'INTEGRATIONS_MOMO_BACKEND',
    'apps.integrations.backends.NoOpMoMoBackend',
)

# Approved external imaging viewers only; no wildcard hosts or embedded access tokens.
PACS_VIEWER_ALLOWED_HOSTS = [host.strip().lower() for host in os.getenv("PACS_VIEWER_ALLOWED_HOSTS", "").split(",") if host.strip()]

REQUIRE_ADMIN_MFA = os.getenv("REQUIRE_ADMIN_MFA", "1") == "1"
OTP_TOTP_ISSUER = "Clinic Staff"
OTP_TOTP_THROTTLE_FACTOR = 2

REQUIRE_SERVICE_SETUP = os.getenv("REQUIRE_SERVICE_SETUP", "1") == "1"

# Independent businesses use separate tenant deployments, never a shared database.
OWNER_CONTROL_PLANE = os.getenv("OWNER_CONTROL_PLANE", "0") == "1"
TENANT_PUBLIC_ORIGIN = os.getenv("TENANT_PUBLIC_ORIGIN", "")
TENANT_KEY = os.getenv("TENANT_KEY", "")
TENANT_SUPPORT_SECRET = os.getenv("TENANT_SUPPORT_SECRET", "")
TENANT_CONTROL_ORIGIN = os.getenv("TENANT_CONTROL_ORIGIN", "")
