from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from charging_system.services.car_service import (
    Start_Charging, End_Charging, Query_Charging_State,
    Modify_Amount, Modify_Mode
)
from charging_system.services.dispatch_service import E_chargingRequest
from charging_system.services.bill_service import Request_Bill, Request_DetailedList


@csrf_exempt
def charging_request(request):
    """车主发起充电请求：?car_id=XXX&mode=F&request_amount=50"""
    car_id = request.GET.get('car_id', '').strip()
    mode = request.GET.get('mode', 'T').strip()
    try:
        request_amount = float(request.GET.get('request_amount', 0))
    except (ValueError, TypeError):
        return JsonResponse({"success": False, "message": "请求充电量必须为数字"})

    if not car_id:
        return JsonResponse({"success": False, "message": "车牌号不能为空"})

    result = E_chargingRequest(car_id, mode, request_amount)
    return JsonResponse(result)


@csrf_exempt
def query_state(request):
    """车主实时查询充电状态：?car_id=XXX"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return JsonResponse({"success": False, "message": "车牌号不能为空"})
    result = Query_Charging_State(car_id)
    return JsonResponse(result)


@csrf_exempt
def modify_amount(request):
    """车主中途修改目标充电量：?car_id=XXX&new_amount=60"""
    car_id = request.GET.get('car_id', '').strip()
    try:
        new_amount = float(request.GET.get('new_amount', 0))
    except (ValueError, TypeError):
        return JsonResponse({"success": False, "message": "新目标充电量必须为数字"})

    if not car_id:
        return JsonResponse({"success": False, "message": "车牌号不能为空"})

    result = Modify_Amount(car_id, new_amount)
    return JsonResponse(result)


@csrf_exempt
def modify_mode(request):
    """车主中途切换快慢充模式：?car_id=XXX&new_mode=T"""
    car_id = request.GET.get('car_id', '').strip()
    new_mode = request.GET.get('new_mode', 'T').strip().upper()

    if not car_id:
        return JsonResponse({"success": False, "message": "车牌号不能为空"})

    if new_mode not in ('F', 'T'):
        return JsonResponse({"success": False, "message": "模式必须为 F(快充) 或 T(慢充)"})

    result = Modify_Mode(car_id, new_mode)
    return JsonResponse(result)


@csrf_exempt
def cancel_charging(request):
    """车主主动取消/结束充电：?car_id=XXX"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return JsonResponse({"success": False, "message": "车牌号不能为空"})

    ret = End_Charging(car_id)
    if ret == 1:
        bill = Request_Bill(car_id)
        return JsonResponse({"success": True, "message": "充电已结束", "bill": bill})
    return JsonResponse({"success": False, "message": "结束充电失败，车辆可能不在充电中"})


@csrf_exempt
def get_bill(request):
    """车主获取最终账单：?car_id=XXX"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return JsonResponse({"success": False, "message": "车牌号不能为空"})
    result = Request_Bill(car_id)
    return JsonResponse(result)


@csrf_exempt
def get_detailed_list(request):
    """车主获取充电详单：?car_id=XXX"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return JsonResponse({"success": False, "message": "车牌号不能为空"})
    result = Request_DetailedList(car_id)
    return JsonResponse({"success": True, "car_id": car_id, "details": result})


def client_page(request):
    """车主端极简操作页面"""
    return render(request, 'client.html')
