from django.contrib import admin
from charging_system.models import ChargePile, CarState, BillRecord

@admin.register(ChargePile)
class ChargePileAdmin(admin.ModelAdmin):
    list_display = ('pile_id', 'mode', 'status', 'current_car_id', 'total_charge_amount', 'total_charge_times')
    list_filter = ('mode', 'status')
    search_fields = ('pile_id',)

@admin.register(CarState)
class CarStateAdmin(admin.ModelAdmin):
    list_display = ('car_id', 'mode', 'status', 'pile', 'queue_index', 'charged_amount', 'total_fee')
    list_filter = ('status', 'mode')
    search_fields = ('car_id',)

@admin.register(BillRecord)
class BillRecordAdmin(admin.ModelAdmin):
    list_display = ('bill_id', 'car_id', 'pile_id', 'charge_amount', 'total_fee', 'start_time', 'end_time')
    search_fields = ('car_id', 'pile_id')