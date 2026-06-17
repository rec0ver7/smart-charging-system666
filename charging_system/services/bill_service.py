from datetime import datetime, timedelta
from typing import List
from django.db.models import Sum
from django.utils import timezone
from charging_system.models import CarState, BillRecord

# 📢 大作业硬性业务参数
SERVICE_FEE_RATE = 0.8  # 固定服务费率：0.8元/度
TIME_SCALE = 60.0       # 时间放大系数：真实1秒 = 模拟1分钟（真实1分钟=模拟1小时）

def get_simulated_time(real_start: datetime, real_end: datetime) -> float:
    """
    根据时间跨度系数，计算转换后的模拟充电时长（单位：小时）
    """
    if not real_start or not real_end:
        return 0.0
    real_duration_seconds = (real_end - real_start).total_seconds()
    # 模拟秒数 = 真实秒数 * TIME_SCALE
    simulated_seconds = real_duration_seconds * TIME_SCALE
    return max(simulated_seconds / 3600.0, 0.0)


def _get_time_period_price(hour: int) -> float:
    """
    大作业分时计费规则引擎（峰平谷电价）：
    - 10:00-15:00, 18:00-21:00：峰时电价 1.0 元/度
    - 7:00-10:00, 15:00-18:00, 21:00-23:00：平时电价 0.7 元/度
    - 其他深夜/凌晨时间（0:00-7:00, 23:00-24:00）：谷时电价 0.4 元/度
    """
    if 10 <= hour < 15 or 18 <= hour < 21:
        return 1.0
    if 7 <= hour < 10 or 15 <= hour < 18 or 21 <= hour < 23:
        return 0.7
    return 0.4


def calculate_phase_fee(start_time: datetime, end_time: datetime, mode: str) -> tuple:
    """
    分时费率分段积分算法：根据车辆充电的绝对起止模拟时间，计算该片段的电费、服务费和电量。
    快充速度: 30度/小时，慢充速度: 10度/小时
    """
    rate = 30.0 if mode == 'F' else 10.0
    simulated_hours = get_simulated_time(start_time, end_time)
    total_amount = simulated_hours * rate
    
    # 简易分段积分：根据起始和结束时段的中间值决定当前片段的费率
    # 真实企业级或复杂模拟下可按小时切片，大作业随堂演示采用当前小时的电价判定即可
    price_per_kwh = _get_time_period_price(end_time.hour)
    
    charge_fee = total_amount * price_per_kwh
    service_fee = total_amount * SERVICE_FEE_RATE
    return round(total_amount, 4), round(charge_fee, 4), round(service_fee, 4)


def Request_DetailedList(car_id: str) -> List[dict]:
    """
    【C组员核心接口】：查询车辆的所有计费详单明细（供前端渲染）
    """
    records = BillRecord.objects.filter(car_id=car_id).order_by('start_time')
    detailed_lists = []
    for idx, r in enumerate(records):
        detailed_lists.append({
            "detail_index": idx + 1,
            "pile_id": r.pile_id,
            "charge_amount": round(r.charge_amount, 2),
            "start_time": r.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": r.end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": round(r.charge_duration_minutes, 1),
            "charge_fee": round(r.charge_fee, 2),
            "service_fee": round(r.service_fee, 2),
            "total_fee": round(r.total_fee, 2)
        })
    return detailed_lists


def Request_Bill(car_id: str) -> dict:
    """
    【C组员核心接口】：生成车辆最终合并的总账单
    """
    summary = BillRecord.objects.filter(car_id=car_id).aggregate(
        total_amount=Sum('charge_amount'),
        total_c_fee=Sum('charge_fee'),
        total_s_fee=Sum('service_fee'),
        total_t_fee=Sum('total_fee')
    )
    
    if summary['total_amount'] is not None:
        return {
            "success": True,
            "car_id": car_id,
            "is_finished": True,
            "total_amount": round(summary['total_amount'], 2),
            "total_charge_fee": round(summary['total_c_fee'], 2),
            "total_service_fee": round(summary['total_s_fee'], 2),
            "total_bill_fee": round(summary['total_t_fee'], 2),
            "message": "充电已结束，最终账单已出具。"
        }
    
    # 兜底动态计算
    try:
        car = CarState.objects.get(car_id=car_id)
        s_fee = car.charged_amount * SERVICE_FEE_RATE
        return {
            "success": True,
            "car_id": car_id,
            "is_finished": False,
            "total_amount": round(car.charged_amount, 2),
            "total_charge_fee": round(max(car.total_fee - s_fee, 0.0), 2),
            "total_service_fee": round(s_fee, 2),
            "total_bill_fee": round(car.total_fee, 2),
            "message": "车辆尚未最终结算，当前为实时动态累计费用。"
        }
    except CarState.DoesNotExist:
        return {"success": False, "message": f"未找到车辆 {car_id} 的账单记录"}