from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from charging_system.services.car_service import (
    Start_Charging, End_Charging, Query_Charging_State,
    Modify_Amount, Modify_Mode
)
from charging_system.services.dispatch_service import E_chargingRequest, handle_pile_fault
from charging_system.services.bill_service import Request_Bill, Request_DetailedList
from charging_system.services.pile_service import (
    powerOn, powerOff, setParameters, Query_PileState, Query_QueueState
)


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


@csrf_exempt
def query_pile_state(request):
    """管理大屏查询充电桩状态：?pile_id=XXX（可选，不传则查询所有）"""
    pile_id = request.GET.get('pile_id', '').strip()
    if pile_id:
        result = Query_PileState(pile_id)
    else:
        result = Query_PileState()
    return JsonResponse(result)


@csrf_exempt
def query_queue_state(request):
    """管理大屏查询充电桩专属队列：?pile_id=XXX"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return JsonResponse({"success": False, "message": "充电桩ID不能为空"})
    result = Query_QueueState(pile_id)
    return JsonResponse(result)


@csrf_exempt
def simulate_fault(request):
    """管理大屏模拟充电桩故障：?pile_id=XXX"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return JsonResponse({"success": False, "message": "充电桩ID不能为空"})
    result = handle_pile_fault(pile_id)
    return JsonResponse(result)


@csrf_exempt
def pile_power_on(request):
    """管理大屏开启充电桩：?pile_id=XXX"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return JsonResponse({"success": False, "message": "充电桩ID不能为空"})
    result = powerOn(pile_id)
    return JsonResponse(result)


@csrf_exempt
def pile_power_off(request):
    """管理大屏关闭充电桩：?pile_id=XXX"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return JsonResponse({"success": False, "message": "充电桩ID不能为空"})
    result = powerOff(pile_id)
    return JsonResponse(result)


@csrf_exempt
def set_pile_parameters(request):
    """管理大屏在线调整电价参数"""
    try:
        peak_price = float(request.GET.get('peak_price', '0')) or None
    except (ValueError, TypeError):
        peak_price = None
    try:
        normal_price = float(request.GET.get('normal_price', '0')) or None
    except (ValueError, TypeError):
        normal_price = None
    try:
        valley_price = float(request.GET.get('valley_price', '0')) or None
    except (ValueError, TypeError):
        valley_price = None
    try:
        service_fee_rate = float(request.GET.get('service_fee_rate', '0')) or None
    except (ValueError, TypeError):
        service_fee_rate = None

    result = setParameters(peak_price, normal_price, valley_price, service_fee_rate)
    return JsonResponse(result)


def client_page(request):
    """车主端极简操作页面"""
    return render(request, 'client.html')


def admin_dashboard(request):
    """管理大屏页面"""
    return render(request, 'admin_dashboard.html')
