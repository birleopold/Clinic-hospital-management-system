from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.integrations.webhooks import sms_delivery
from apps.accounts import approval_views, tenant_views, tenant_portal_views, mfa_views, branch_views, structure_views, setup_views as account_setup_views
from apps.accounts.token_views import StaffTokenView, StaffRefreshView

urlpatterns = [
    path('accounts/approvals/',approval_views.matrix,name='approval-matrix'),
    path('accounts/tenants/', tenant_portal_views.console, name='tenant-console'),
    path('accounts/tenants/support/', tenant_portal_views.support_queue, name='tenant-support-queue'),
    path('accounts/tenants/<int:pk>/workspace/', tenant_portal_views.detail, name='tenant-detail'),
    path('accounts/tenants/<int:tenant_pk>/cases/<int:pk>/', tenant_portal_views.support_case, name='tenant-support-case'),
    path('accounts/tenants/policy/', tenant_views.policy, name='tenant-policy'),
    path('accounts/tenants/<int:pk>/', tenant_views.action, name='tenant-action'),
    path('accounts/support/accept/', tenant_views.accept, name='owner-support-accept'),
    path('accounts/support/sessions/', tenant_views.sessions, name='owner-support-sessions'),
    path('accounts/structure/<slug:kind>/',structure_views.structure,name='facility-structure'),
    path('accounts/structure/<slug:kind>/<int:pk>/',structure_views.structure,name='facility-structure-edit'),
    path('accounts/branding/<int:pk>/logo/',account_setup_views.logo,name='facility-logo'),
    path('accounts/control/',account_setup_views.control,name='owner-control'),
    path('accounts/setup/',account_setup_views.configure,name='facility-configure'),
    path('accounts/staff/',account_setup_views.staff,name='facility-staff'),
    path('accounts/staff/<int:pk>/',account_setup_views.staff_access,name='facility-staff-access'),
    path('accounts/facility/',branch_views.select,name='facility-select'),
    path('accounts/mfa/',mfa_views.challenge,name='mfa-verify'),
    path('accounts/mfa/enroll/',mfa_views.enroll,name='mfa-enroll'),
    path('integrations/sms/delivery/', sms_delivery, name='sms-delivery'),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),  # login/logout/password
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
    path('api/auth/token/', StaffTokenView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', StaffRefreshView.as_view(), name='token_refresh'),
    path('api/', include('apps.appointments.urls')),
    path('api/', include('apps.encounters.urls')),
    path('api/', include('apps.reports.urls')),
    path('api/', include('apps.demographics.urls')),
    path('api/', include('apps.orders.urls')),
    path('api/', include('apps.pharmacy.urls')),
    path('api/', include('apps.billing.urls')),
    path('api/', include('apps.inventory.urls')),
    path('', include('apps.operations.urls')),
    # UI routes
    path('', include('apps.appointments.ui_urls')),
    path('', include('apps.encounters.ui_urls')),
    path('', include('apps.pharmacy.ui_urls')),
    path('', include('apps.inventory.ui_urls')),
    path('', include('apps.reports.ui_urls')),
    path('', include('apps.portal.ui_urls')),
    path('', include('apps.billing.ui_urls')),
    path('', include('apps.demographics.ui_urls')),
    path('', include('apps.orders.ui_urls')),
]

# Clinical documents are served only through authenticated download views.
