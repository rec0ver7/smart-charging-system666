from django.db import transaction
from django.utils import timezone
from charging_system.models import ChargePile, CarState, BillRecord
from charging_system.services.dispatch_service import priority_schedule
from charging_system.services.car_service import calc_display_charge

# 全局电价参数（支持运行时动态调整）
PEAK_HOURS = [(10, 15), (18, 21)]       # 峰时时段
NORMAL_HOURS = [(7, 10), (15, 18), (21, 23)]  # 平时时段
PEAK_PRICE = 1.0       # 峰时电价（元/度）
NORMAL_PRICE = 0.7     # 平时电价（元/度）
VALLEY_PRICE = 0.4     # 谷时电价（元/度）
SERVICE_FEE_RATE = 0.8 # 服务费（元/度）
FAST_RATE = 30.0       # 快充速度（度/小时）
TRICKLE_RATE = 10.0    # 慢充速度（度/小时）


def powerOn(pile_id: str) -> dict:
    """
    【组员D负责】：硬启停控制 - 开启充电桩
    将指定充电桩从故障或离线状态切换为可用状态
    """
    try:
        with transaction.atomic():
            try:
                pile = ChargePile.objects.select_for_update().get(pile_id=pile_id)
            except ChargePile.DoesNotExist:
                return {"success": False, "message": f"充电桩 {pile_id} 不存在"}
            
            if pile.status == 'IDLE':
                return {"success": True, "message": f"充电桩 {pile_id} 已处于开启状态"}
            
            # 将故障状态切换为空闲状态
            pile.status = 'IDLE'
            pile.current_car_id = None
            pile.save()
            
            return {"success": True, "message": f"充电桩 {pile_id} 已成功开启"}
    except Exception as e:
        return {"success": False, "message": f"开启充电桩失败: {str(e)}"}


def powerOff(pile_id: str) -> dict:
    """
    【组员D负责】：硬启停控制 - 关闭充电桩
    将指定充电桩强制关闭（无论当前状态如何），用于紧急维护或故障处理
    """
    try:
        with transaction.atomic():
            try:
                pile = ChargePile.objects.select_for_update().get(pile_id=pile_id)
            except ChargePile.DoesNotExist:
                return {"success": False, "message": f"充电桩 {pile_id} 不存在"}
            
            if pile.status == 'FAULT':
                return {"success": True, "message": f"充电桩 {pile_id} 已处于关闭状态"}
            
            # 记录当前正在充电的车辆
            affected_car_id = pile.current_car_id
            
            # 强制设置为故障状态
            pile.status = 'FAULT'
            pile.current_car_id = None
            pile.save()
            
            # 如果有车辆正在充电，需要处理
            if affected_car_id:
                try:
                    car = CarState.objects.select_for_update().get(car_id=affected_car_id)
                    if car.status == 'CHARGING':
                        car.status = 'FAULT_WAITING'
                        car.pile = None
                        car.queue_index = 0
                        car.save()
                        # 尝试重调度该车辆
                        res = priority_schedule(affected_car_id)
                        return {
                            "success": True,
                            "message": f"充电桩 {pile_id} 已强制关闭",
                            "affected_car": affected_car_id,
                            "reschedule_result": res
                        }
                except CarState.DoesNotExist:
                    pass
            
            return {"success": True, "message": f"充电桩 {pile_id} 已成功关闭"}
    except Exception as e:
        return {"success": False, "message": f"关闭充电桩失败: {str(e)}"}


def setParameters(peak_price: float = None, normal_price: float = None, 
                  valley_price: float = None, service_fee_rate: float = None,
                  fast_rate: float = None, trickle_rate: float = None) -> dict:
    """
    【组员D负责】：在线调整电价参数
    动态修改峰平谷电价、服务费率和充电速度等运行参数
    参数为 None 表示不修改该参数
    """
    global PEAK_PRICE, NORMAL_PRICE, VALLEY_PRICE, SERVICE_FEE_RATE, FAST_RATE, TRICKLE_RATE
    
    try:
        changes = []
        
        if peak_price is not None:
            if peak_price <= 0:
                return {"success": False, "message": "峰时电价必须大于0"}
            PEAK_PRICE = peak_price
            changes.append(f"峰时电价: {peak_price} 元/度")
        
        if normal_price is not None:
            if normal_price <= 0:
                return {"success": False, "message": "平时电价必须大于0"}
            NORMAL_PRICE = normal_price
            changes.append(f"平时电价: {normal_price} 元/度")
        
        if valley_price is not None:
            if valley_price <= 0:
                return {"success": False, "message": "谷时电价必须大于0"}
            VALLEY_PRICE = valley_price
            changes.append(f"谷时电价: {valley_price} 元/度")
        
        if service_fee_rate is not None:
            if service_fee_rate < 0:
                return {"success": False, "message": "服务费率不能为负数"}
            SERVICE_FEE_RATE = service_fee_rate
            changes.append(f"服务费率: {service_fee_rate} 元/度")
        
        if fast_rate is not None:
            if fast_rate <= 0:
                return {"success": False, "message": "快充速度必须大于0"}
            FAST_RATE = fast_rate
            changes.append(f"快充速度: {fast_rate} 度/小时")
        
        if trickle_rate is not None:
            if trickle_rate <= 0:
                return {"success": False, "message": "慢充速度必须大于0"}
            TRICKLE_RATE = trickle_rate
            changes.append(f"慢充速度: {trickle_rate} 度/小时")
        
        if not changes:
            return {"success": False, "message": "未提供任何有效参数修改"}
        
        return {
            "success": True,
            "message": "参数调整成功",
            "changes": changes,
            "current_parameters": {
                "peak_price": PEAK_PRICE,
                "normal_price": NORMAL_PRICE,
                "valley_price": VALLEY_PRICE,
                "service_fee_rate": SERVICE_FEE_RATE,
                "fast_rate": FAST_RATE,
                "trickle_rate": TRICKLE_RATE
            }
        }
    except Exception as e:
        return {"success": False, "message": f"参数调整失败: {str(e)}"}


def Start_ChargingPile(pile_id: str) -> dict:
    """
    【组员D负责】：激活状态机
    检查充电桩状态，如果空闲则自动从专属队列中调度车辆上桩开始充电
    """
    try:
        with transaction.atomic():
            try:
                pile = ChargePile.objects.select_for_update().get(pile_id=pile_id)
            except ChargePile.DoesNotExist:
                return {"success": False, "message": f"充电桩 {pile_id} 不存在"}
            
            # 检查充电桩状态
            if pile.status == 'FAULT':
                return {"success": False, "message": f"充电桩 {pile_id} 处于故障状态，无法激活"}
            
            if pile.status == 'CHARGING':
                return {"success": True, "message": f"充电桩 {pile_id} 正在充电中"}
            
            # 查找专属队列中的第一辆车
            next_car = pile.cars_in_queue.filter(status='QUEUEING').order_by('queue_index', 'request_time').first()
            
            if not next_car:
                # 如果专属队列没车，尝试从等候区调度
                from charging_system.services.dispatch_service import time_order_schedule
                res = time_order_schedule()
                return {
                    "success": True,
                    "message": f"充电桩 {pile_id} 已激活，但专属队列无车，已触发全局调度",
                    "dispatch_result": res
                }
            
            # 激活队列中的第一辆车
            next_car.status = 'CHARGING'
            next_car.start_time = next_car.start_time or timezone.now()
            next_car.last_update_time = timezone.now()
            next_car.queue_index = 0
            next_car.save()
            
            # 更新充电桩状态
            pile.status = 'CHARGING'
            pile.current_car_id = next_car.car_id
            pile.total_charge_times += 1
            pile.save()
            
            # 其他排队车辆顺位前移
            pile.cars_in_queue.filter(status='QUEUEING').exclude(car_id=next_car.car_id).update(queue_index=0)
            
            return {
                "success": True,
                "message": f"充电桩 {pile_id} 状态机已激活",
                "car_id": next_car.car_id,
                "action": "STARTED"
            }
    except Exception as e:
        return {"success": False, "message": f"激活状态机失败: {str(e)}"}


def get_pile_parameters() -> dict:
    """
    获取当前电价参数配置
    """
    return {
        "peak_price": PEAK_PRICE,
        "normal_price": NORMAL_PRICE,
        "valley_price": VALLEY_PRICE,
        "service_fee_rate": SERVICE_FEE_RATE,
        "fast_rate": FAST_RATE,
        "trickle_rate": TRICKLE_RATE,
        "peak_hours": PEAK_HOURS,
        "normal_hours": NORMAL_HOURS
    }


def auto_tick_piles():
    """
    驱动模拟推进：遍历所有正在充电的桩，动态计算当前车是否已充满。
    若已满则自动结算、释放桩、触发下一辆车入队。
    管理端每次轮询时调用，保证队列持续流动。
    """
    from charging_system.services.bill_service import calculate_phase_fee
    from charging_system.services.dispatch_service import time_slice_schedule

    try:
        with transaction.atomic():
            charging_piles = ChargePile.objects.select_for_update().filter(status='CHARGING')
            for pile in charging_piles:
                if not pile.current_car_id:
                    continue
                try:
                    car = CarState.objects.select_for_update().get(car_id=pile.current_car_id, status='CHARGING')
                except CarState.DoesNotExist:
                    continue

                disp_charged, disp_fee = calc_display_charge(car)
                if disp_charged < car.request_amount:
                    continue  # 还没充满，跳过

                # 充满：创建最后一段详单、更新车辆状态、释放桩
                now_time = timezone.now()
                if car.last_update_time:
                    amt, c_fee, s_fee = calculate_phase_fee(car.last_update_time, now_time, car.mode)
                    actual_amt = min(amt, car.request_amount - car.charged_amount)
                    if actual_amt > 0:
                        ratio = actual_amt / amt if amt > 0 else 1.0
                        BillRecord.objects.create(
                            car_id=car.car_id,
                            pile_id=pile.pile_id,
                            charge_amount=actual_amt,
                            start_time=car.last_update_time,
                            end_time=now_time,
                            charge_duration_minutes=(now_time - car.last_update_time).total_seconds() * 60 / 3600,
                            charge_fee=c_fee * ratio,
                            service_fee=s_fee * ratio,
                            total_fee=(c_fee + s_fee) * ratio
                        )

                if car.start_time:
                    dur = (now_time - car.start_time).total_seconds() * 60 / 3600
                    pile.total_charge_duration_minutes += dur
                pile.total_charge_amount += car.charged_amount
                pile.total_charge_times += 1

                car.charged_amount = disp_charged
                car.total_fee = disp_fee
                car.status = 'FINISHED'
                car.end_time = now_time
                car.pile = None
                car.queue_index = 0
                car.save()

                pile.current_car_id = None
                pile.status = 'IDLE'
                pile.save()

                # 唤醒队列中下一辆车
                time_slice_schedule(pile.pile_id)
    except Exception:
        pass  # tick 失败不阻塞查询


def Query_PileState(pile_id: str = None) -> dict:
    """
    【组员E负责】：收集充电桩运行指标
    如果提供pile_id则查询单个充电桩，否则查询所有充电桩的状态
    返回5个关键运行指标：状态、当前充电车辆、累计充电量、累计充电次数、累计充电时长
    """
    try:
        if pile_id:
            # 查询单个充电桩
            try:
                pile = ChargePile.objects.get(pile_id=pile_id)
            except ChargePile.DoesNotExist:
                return {"success": False, "message": f"充电桩 {pile_id} 不存在"}
            
            # 获取当前正在充电的车辆信息（动态计算实时电量）
            current_car_info = None
            if pile.current_car_id:
                try:
                    car = CarState.objects.get(car_id=pile.current_car_id)
                    disp_charged, disp_fee = calc_display_charge(car)
                    current_car_info = {
                        "car_id": car.car_id,
                        "mode": car.mode,
                        "charged_amount": disp_charged,
                        "request_amount": round(car.request_amount, 2),
                        "total_fee": disp_fee
                    }
                except CarState.DoesNotExist:
                    pass

            return {
                "success": True,
                "pile_id": pile.pile_id,
                "mode": pile.mode,
                "mode_display": pile.get_mode_display(),
                "status": pile.status,
                "status_display": pile.get_status_display(),
                "current_car": current_car_info,
                "metrics": {
                    "total_charge_amount": round(pile.total_charge_amount, 2),
                    "total_charge_times": pile.total_charge_times,
                    "total_charge_duration_minutes": round(pile.total_charge_duration_minutes, 2),
                    "queue_length": pile.cars_in_queue.filter(status='QUEUEING').count(),
                    "average_charge_per_time": round(
                        pile.total_charge_amount / max(pile.total_charge_times, 1), 2
                    )
                }
            }
        else:
            # 先驱动一轮模拟推进，让充满的车自动出队、排队车上桩
            auto_tick_piles()

            # 查询所有充电桩
            piles = ChargePile.objects.all()
            result = []
            
            for pile in piles:
                current_car_info = None
                if pile.current_car_id:
                    try:
                        car = CarState.objects.get(car_id=pile.current_car_id)
                        disp_charged, disp_fee = calc_display_charge(car)
                        current_car_info = {
                            "car_id": car.car_id,
                            "mode": car.mode,
                            "charged_amount": disp_charged,
                            "request_amount": round(car.request_amount, 2),
                            "total_fee": disp_fee
                        }
                    except CarState.DoesNotExist:
                        pass
                
                result.append({
                    "pile_id": pile.pile_id,
                    "mode": pile.mode,
                    "mode_display": pile.get_mode_display(),
                    "status": pile.status,
                    "status_display": pile.get_status_display(),
                    "current_car": current_car_info,
                    "metrics": {
                        "total_charge_amount": round(pile.total_charge_amount, 2),
                        "total_charge_times": pile.total_charge_times,
                        "total_charge_duration_minutes": round(pile.total_charge_duration_minutes, 2),
                        "queue_length": pile.cars_in_queue.filter(status='QUEUEING').count(),
                        "average_charge_per_time": round(
                            pile.total_charge_amount / max(pile.total_charge_times, 1), 2
                        )
                    }
                })
            
            return {"success": True, "piles": result}
    except Exception as e:
        return {"success": False, "message": f"查询充电桩状态失败: {str(e)}"}


def Query_QueueState(pile_id: str) -> dict:
    """
    【组员E负责】：获取充电桩专属队列车辆列表
    返回指定充电桩后方专属队列中的所有车辆信息（按排队顺序）
    """
    try:
        try:
            pile = ChargePile.objects.get(pile_id=pile_id)
        except ChargePile.DoesNotExist:
            return {"success": False, "message": f"充电桩 {pile_id} 不存在"}
        
        # 获取专属队列中的车辆（按排队顺序）
        queue_cars = CarState.objects.filter(
            pile=pile, status='QUEUEING'
        ).order_by('queue_index', 'request_time')
        
        queue_list = []
        for car in queue_cars:
            queue_list.append({
                "car_id": car.car_id,
                "mode": car.mode,
                "mode_display": car.get_mode_display(),
                "queue_index": car.queue_index,
                "request_amount": round(car.request_amount, 2),
                "charged_amount": round(car.charged_amount, 2),
                "remaining_amount": round(max(car.request_amount - car.charged_amount, 0), 2),
                "total_fee": round(car.total_fee, 2),
                "request_time": car.request_time.strftime("%Y-%m-%d %H:%M:%S"),
                "estimated_wait_minutes": car.queue_index * 30  # 预估等待时间（假设每车平均充电30分钟）
            })
        
        # 获取当前正在充电的车辆（动态计算实时电量）
        current_car_info = None
        if pile.current_car_id:
            try:
                car = CarState.objects.get(car_id=pile.current_car_id)
                disp_charged, disp_fee = calc_display_charge(car)
                current_car_info = {
                    "car_id": car.car_id,
                    "mode": car.mode,
                    "mode_display": car.get_mode_display(),
                    "request_amount": round(car.request_amount, 2),
                    "charged_amount": disp_charged,
                    "remaining_amount": round(max(car.request_amount - disp_charged, 0), 2),
                    "total_fee": disp_fee,
                    "start_time": car.start_time.strftime("%Y-%m-%d %H:%M:%S") if car.start_time else None
                }
            except CarState.DoesNotExist:
                pass
        
        return {
            "success": True,
            "pile_id": pile.pile_id,
            "pile_mode": pile.mode,
            "pile_mode_display": pile.get_mode_display(),
            "pile_status": pile.status,
            "current_car": current_car_info,
            "queue_length": len(queue_list),
            "max_queue_limit": 4,
            "queue_list": queue_list
        }
    except Exception as e:
        return {"success": False, "message": f"查询队列状态失败: {str(e)}"}