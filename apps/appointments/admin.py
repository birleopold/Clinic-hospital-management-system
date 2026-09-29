from django.contrib import admin
from .models import Appointment, QueueTicket, DoctorWeeklyAvailability, DoctorTimeOff

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('id','patient','clinician','scheduled_for','status')
    list_filter = ('status',)
    search_fields = ('patient__first_name','patient__last_name','reason_for_visit')

@admin.register(QueueTicket)
class QueueTicketAdmin(admin.ModelAdmin):
    list_display = ('id','patient','service','status','created_at','started_at','finished_at','assigned_to')
    list_filter = ('service','status')
    search_fields = ('patient__first_name','patient__last_name','notes')


@admin.register(DoctorWeeklyAvailability)
class DoctorWeeklyAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        'clinician','day_of_week','start_time','end_time',
        'default_duration_minutes','buffer_minutes','is_active','location'
    )
    list_filter = ('day_of_week','is_active')
    search_fields = ('clinician__username',)


@admin.register(DoctorTimeOff)
class DoctorTimeOffAdmin(admin.ModelAdmin):
    list_display = ('clinician','start','end','reason')
    list_filter = ('clinician',)
    search_fields = ('clinician__username','reason')
