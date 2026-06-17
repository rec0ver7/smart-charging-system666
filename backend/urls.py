from django.contrib import admin
from django.urls import path
from charging_system import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # 页面
    path('', views.client_page, name='client_page'),
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),

    # 车主端接口
    path('api/charging_request', views.charging_request, name='charging_request'),
    path('api/query_state', views.query_state, name='query_state'),
    path('api/modify_amount', views.modify_amount, name='modify_amount'),
    path('api/modify_mode', views.modify_mode, name='modify_mode'),
    path('api/cancel_charging', views.cancel_charging, name='cancel_charging'),
    path('api/get_bill', views.get_bill, name='get_bill'),
    path('api/get_detailed_list', views.get_detailed_list, name='get_detailed_list'),

    # 管理大屏接口
    path('api/query_pile_state', views.query_pile_state, name='query_pile_state'),
    path('api/query_queue_state', views.query_queue_state, name='query_queue_state'),
    path('api/simulate_fault', views.simulate_fault, name='simulate_fault'),
    path('api/pile_power_on', views.pile_power_on, name='pile_power_on'),
    path('api/pile_power_off', views.pile_power_off, name='pile_power_off'),
    path('api/set_pile_parameters', views.set_pile_parameters, name='set_pile_parameters'),
]
