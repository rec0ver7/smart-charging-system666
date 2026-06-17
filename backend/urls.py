from django.contrib import admin
from django.urls import path
from charging_system import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # 页面
    path('', views.client_page, name='client_page'),

    # 车主端接口
    path('api/charging_request', views.charging_request, name='charging_request'),
    path('api/query_state', views.query_state, name='query_state'),
    path('api/modify_amount', views.modify_amount, name='modify_amount'),
    path('api/modify_mode', views.modify_mode, name='modify_mode'),
    path('api/cancel_charging', views.cancel_charging, name='cancel_charging'),
    path('api/get_bill', views.get_bill, name='get_bill'),
    path('api/get_detailed_list', views.get_detailed_list, name='get_detailed_list'),
]
