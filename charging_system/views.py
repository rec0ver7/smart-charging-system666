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


def _err(msg, status=400):
    """统一错误响应"""
    return JsonResponse({"success": False, "message": msg}, status=status)


def _ok(data=None, **kwargs):
    """统一成功响应"""
    resp = {"success": True}
    if data is not None:
        resp.update(data)
    resp.update(kwargs)
    return JsonResponse(resp)


@csrf_exempt
def charging_request(request):
    """车主发起充电请求"""
    car_id = request.GET.get('car_id', '').strip()
    mode = request.GET.get('mode', 'T').strip()
    try:
        request_amount = float(request.GET.get('request_amount', 0))
    except (ValueError, TypeError):
        return _err("请求充电量必须为数字")

    if not car_id:
        return _err("车牌号不能为空")

    result = E_chargingRequest(car_id, mode, request_amount)
    status = 200 if result.get('success') else 400
    return JsonResponse(result, status=status)


@csrf_exempt
def query_state(request):
    """车主实时查询充电状态"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return _err("车牌号不能为空")
    result = Query_Charging_State(car_id)
    status = 200 if result.get('success') else 404
    return JsonResponse(result, status=status)


@csrf_exempt
def modify_amount(request):
    """车主中途修改目标充电量"""
    car_id = request.GET.get('car_id', '').strip()
    try:
        new_amount = float(request.GET.get('new_amount', 0))
    except (ValueError, TypeError):
        return _err("新目标充电量必须为数字")

    if not car_id:
        return _err("车牌号不能为空")

    result = Modify_Amount(car_id, new_amount)
    status = 200 if result.get('success') else 400
    return JsonResponse(result, status=status)


@csrf_exempt
def modify_mode(request):
    """车主中途切换快慢充模式"""
    car_id = request.GET.get('car_id', '').strip()
    new_mode = request.GET.get('new_mode', 'T').strip().upper()

    if not car_id:
        return _err("车牌号不能为空")

    if new_mode not in ('F', 'T'):
        return _err("模式必须为 F(快充) 或 T(慢充)")

    result = Modify_Mode(car_id, new_mode)
    status = 200 if result.get('success') else 400
    return JsonResponse(result, status=status)


@csrf_exempt
def cancel_charging(request):
    """车主主动取消/结束充电"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return _err("车牌号不能为空")

    ret = End_Charging(car_id)
    if ret == 1:
        bill = Request_Bill(car_id)
        return _ok({"bill": bill}, message="充电已结束")
    return _err("结束充电失败，车辆可能不在充电中")


@csrf_exempt
def get_bill(request):
    """车主获取最终账单"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return _err("车牌号不能为空")
    result = Request_Bill(car_id)
    status = 200 if result.get('success') else 404
    return JsonResponse(result, status=status)


@csrf_exempt
def get_detailed_list(request):
    """车主获取充电详单"""
    car_id = request.GET.get('car_id', '').strip()
    if not car_id:
        return _err("车牌号不能为空")
    result = Request_DetailedList(car_id)
    return JsonResponse({"success": True, "car_id": car_id, "details": result})


@csrf_exempt
def query_pile_state(request):
    """管理大屏查询充电桩状态（不传 pile_id 则查全部）"""
    pile_id = request.GET.get('pile_id', '').strip()
    result = Query_PileState(pile_id) if pile_id else Query_PileState()
    status = 200 if result.get('success') else 404
    return JsonResponse(result, status=status)


@csrf_exempt
def query_queue_state(request):
    """管理大屏查询充电桩专属队列"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return _err("充电桩ID不能为空")
    result = Query_QueueState(pile_id)
    status = 200 if result.get('success') else 404
    return JsonResponse(result, status=status)


@csrf_exempt
def simulate_fault(request):
    """管理大屏模拟充电桩故障"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return _err("充电桩ID不能为空")
    result = handle_pile_fault(pile_id)
    status = 200 if result.get('success') else 400
    return JsonResponse(result, status=status)


@csrf_exempt
def pile_power_on(request):
    """管理大屏开启充电桩"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return _err("充电桩ID不能为空")
    result = powerOn(pile_id)
    status = 200 if result.get('success') else 400
    return JsonResponse(result, status=status)


@csrf_exempt
def pile_power_off(request):
    """管理大屏关闭充电桩"""
    pile_id = request.GET.get('pile_id', '').strip()
    if not pile_id:
        return _err("充电桩ID不能为空")
    result = powerOff(pile_id)
    status = 200 if result.get('success') else 400
    return JsonResponse(result, status=status)


@csrf_exempt
def set_pile_parameters(request):
    """管理大屏在线调整电价参数"""
    def _get_float_param(key):
        val = request.GET.get(key, '')
        if val == '':
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    peak_price = _get_float_param('peak_price')
    normal_price = _get_float_param('normal_price')
    valley_price = _get_float_param('valley_price')
    service_fee_rate = _get_float_param('service_fee_rate')

    result = setParameters(peak_price, normal_price, valley_price, service_fee_rate)
    return JsonResponse(result)


def client_page(request):
    """车主端极简操作页面"""
    return render(request, 'client.html')


def admin_dashboard(request):
    """管理大屏页面"""
    return render(request, 'admin_dashboard.html')
