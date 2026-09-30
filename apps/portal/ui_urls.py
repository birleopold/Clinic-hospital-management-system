from django.urls import path
from . import ui_views, action_views

urlpatterns = [
    path('portal/<str:token>/instructions/<int:pk>/acknowledge/',action_views.acknowledge_instructions,name='portal-instruction-acknowledge'),
    path('portal/<str:token>/appointments/<int:pk>/change/',action_views.change,name='portal-appointment-change'),
    path('portal/<str:token>/feedback/',action_views.feedback,name='portal-feedback'),
    path('portal/<str:token>/revoke/',action_views.revoke,name='portal-self-revoke'),
    path('portal/token', ui_views.token_create_view, name='portal-token-create'),
    path('portal/<str:token>/results/<int:pk>', ui_views.portal_download, name='portal-download'),
    path('portal/<str:token>', ui_views.portal_view, name='portal-view'),
]
