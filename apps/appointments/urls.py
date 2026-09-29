from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    AppointmentViewSet,
    QueueTicketViewSet,
    DoctorWeeklyAvailabilityViewSet,
    DoctorTimeOffViewSet,
)

router = DefaultRouter()
router.register(r'appointments', AppointmentViewSet, basename='appointment')
router.register(r'queue-tickets', QueueTicketViewSet, basename='queue-ticket')
router.register(r'doctor-availability', DoctorWeeklyAvailabilityViewSet, basename='doctor-availability')
router.register(r'doctor-timeoff', DoctorTimeOffViewSet, basename='doctor-timeoff')

urlpatterns = [
    path('', include(router.urls)),
]
