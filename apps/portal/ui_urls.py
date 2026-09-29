from django.urls import path
from . import ui_views

urlpatterns = [
    path('portal/token', ui_views.token_create_view, name='portal-token-create'),
    path('portal/<str:token>/results/<int:pk>', ui_views.portal_download, name='portal-download'),
    path('portal/<str:token>', ui_views.portal_view, name='portal-view'),
]
