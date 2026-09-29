from django.urls import path
from . import ui_views

urlpatterns = [
    path('', ui_views.home_view, name='home'),
    path('queues', ui_views.queue_summary_view, name='queues-summary'),
    path('queues/<str:service>', ui_views.queue_service_view, name='queues-service'),
    path('appointments/schedule', ui_views.calendar_view, name='appointments-calendar'),
    path('appointments/slots', ui_views.appointment_slots_fragment, name='appointments-slots'),
]
