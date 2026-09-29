from django.urls import path
from . import ui_views

urlpatterns = [
    path('portal/<str:token>', ui_views.portal_view, name='portal-view'),
    path('portal/token', ui_views.token_create_view, name='portal-token-create'),
]
