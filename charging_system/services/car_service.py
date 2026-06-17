from datetime import datetime
from django.db import transaction
from django.utils import timezone
from typing import Optional

# 📢 彻底废弃内存 dataclass 和全局字典，直接引入我们建好的正式物理模型
from charging_system.models import CarState, ChargePile, BillRecord
from charging_system.services.bill_service import calculate_phase_fee, TIME_SCALE

# 严格对齐大作业约定的基础参数
FAST_RATE = 30.0        # 快充速度：30度/小时
TRICKLE_RATE = 10.0     # 慢充速度：10度/小时
SERVICE_FEE_RATE = 0.8  # 固定服务费：0.8元/度


def Start_Charging(car_id: str) -> int:
    """
    【组员B负责接口】：控制车辆正式启动充电。
    改动点：利用数据库锁（select_for_update），将对应的车和充电桩从数据库中取出并更新状态。
    """
    try:
        with transaction.atomic():
            try:
                car = CarState.objects.select_for_update().get(car_id=car_id)
            except CarState.DoesNotExist:
                return 0

            if not car.pile:
                return 0

            # 锁定该车关联的物理充电桩
            pile = ChargePile.objects.select_for_update().get(pile_id=car.pile.pile_id)
            
            if pile.status == 'FAULT':
                return 0

            # 如果该桩当前有别的车在充电，且不是自己，则无法启动
            if pile.current_car_id and pile.current_car_id != car_id:
                return 0

            if car.status == 'CHARGING':
                return 1

            # 真正修改数据库中桩与车的状态
            now_time = timezone.now()
            pile.current_car_id = car_id
            pile.status = 'CHARGING'
            pile.save()

            car.status = 'CHARGING'
            car.start_time = car.start_time or now_time
            car.last_update_time = now_time
            car.save()

            return 1
    except Exception:
        return 0


def End_Charging(car_id: str) -> int:
    """
    【组员B负责接口】：用户主动结束充电或充满自动结束。
    改动点：计算这一时间段最终电费，并在物理数据库中创建最终的详单记录（BillRecord），释放充电桩。
    """
    try:
        with transaction.atomic():
            try:
                car = CarState.objects.select_for_update().get(car_id=car_id)
            except CarState.DoesNotExist:
                return 0

            if car.status != 'CHARGING':
                return 0

            now_time = timezone.now()
            pile = car.pile

            # 1. 阶段结算并保存最终详单明细
            if car.last_update_time and pile:
                pile_locked = ChargePile.objects.select_for_update().get(pile_id=pile.pile_id)
                
                # 计算最后这一个片段的电量与费用
                amt, c_fee, s_fee = calculate_phase_fee(car.last_update_time, now_time, car.mode)
                actual_amt = min(amt, car.request_amount - car.charged_amount)
                
                if actual_amt > 0:
                    ratio = actual_amt / amt if amt > 0 else 1.0
                    duration_minutes = (now_time - car.last_update_time).total_seconds() * TIME_SCALE / 60
                    
                    # 落地物理详单表
                    BillRecord.objects.create(
                        car_id=car_id,
                        pile_id=pile.pile_id,
                        charge_amount=actual_amt,
                        start_time=car.last_update_time,
                        end_time=now_time,
                        charge_duration_minutes=duration_minutes,
                        charge_fee=c_fee * ratio,
                        service_fee=s_fee * ratio,
                        total_fee=(c_fee + s_fee) * ratio
                    )
                    car.charged_amount += actual_amt
                    car.total_fee += (c_fee + s_fee) * ratio
                
                # 累加统计并释放充电桩
                duration_total_minutes = 0.0
                if car.start_time:
                    duration_total_minutes = (now_time - car.start_time).total_seconds() * TIME_SCALE / 60
                
                pile_locked.total_charge_amount += car.charged_amount
                pile_locked.total_charge_duration_minutes += duration_total_minutes
                pile_locked.total_charge_times += 1
                pile_locked.current_car_id = None
                pile_locked.status = 'IDLE'
                pile_locked.save()

            # 2. 修改车辆为完结状态
            car.status = 'FINISHED'
            car.end_time = now_time
            car.save()

            # 3. 【核心联动】：如果该桩后方专属队列里还有车在排队，自动唤醒并调度下一个幸运儿上桩
            if pile:
                from charging_system.services.dispatch_service import time_slice_schedule
                time_slice_schedule(pile.pile_id)

            return 1
    except Exception:
        return 0


def Modify_Amount(car_id: str, new_amount: float) -> dict:
    """
    【组员A核心接口】：支持车主中途修改目标充电量。
    若新目标 <= 已充度数，自动触发充电结束与结算。
    """
    if new_amount <= 0:
        return {"success": False, "message": "目标充电量必须大于0"}

    try:
        with transaction.atomic():
            try:
                car = CarState.objects.select_for_update().get(car_id=car_id)
            except CarState.DoesNotExist:
                return {"success": False, "message": f"车辆 {car_id} 不存在"}

            if car.status not in ('CHARGING', 'QUEUEING'):
                return {"success": False, "message": f"车辆状态 {car.status} 不允许修改电量"}

            if new_amount <= car.charged_amount:
                if car.status == 'CHARGING':
                    now_time = timezone.now()
                    pile = car.pile
                    if car.last_update_time and pile:
                        pile = ChargePile.objects.select_for_update().get(pile_id=pile.pile_id)
                        amt, c_fee, s_fee = calculate_phase_fee(car.last_update_time, now_time, car.mode)
                        actual_amt = min(amt, car.request_amount - car.charged_amount)
                        if actual_amt > 0:
                            ratio = actual_amt / amt if amt > 0 else 1.0
                            duration_minutes = (now_time - car.last_update_time).total_seconds() * TIME_SCALE / 60
                            BillRecord.objects.create(
                                car_id=car_id, pile_id=pile.pile_id, charge_amount=actual_amt,
                                start_time=car.last_update_time, end_time=now_time,
                                charge_duration_minutes=duration_minutes,
                                charge_fee=c_fee * ratio, service_fee=s_fee * ratio,
                                total_fee=(c_fee + s_fee) * ratio
                            )
                            car.charged_amount += actual_amt
                            car.total_fee += (c_fee + s_fee) * ratio
                            pile.total_charge_amount += actual_amt
                        if car.start_time:
                            dur = (now_time - car.start_time).total_seconds() * TIME_SCALE / 60
                            pile.total_charge_duration_minutes += dur
                        pile.total_charge_times += 1
                        pile.current_car_id = None
                        pile.status = 'IDLE'
                        pile.save()

                    car.request_amount = new_amount
                    car.status = 'FINISHED'
                    car.end_time = now_time
                    car.save()

                    if pile:
                        from charging_system.services.dispatch_service import time_slice_schedule
                        time_slice_schedule(pile.pile_id)

                    return {"success": True, "action": "FINISHED", "message": "新目标电量不高于已充度数，充电自动结束"}
                else:
                    car.request_amount = new_amount
                    car.status = 'FINISHED'
                    car.end_time = timezone.now()
                    car.pile = None
                    car.queue_index = 0
                    car.save()
                    return {"success": True, "action": "FINISHED", "message": "排队中车辆下调电量至已充度数以下，请求自动取消"}

            old_amount = car.request_amount
            car.request_amount = new_amount
            car.save()
            return {
                "success": True,
                "action": "UPDATED",
                "car_id": car_id,
                "old_amount": round(old_amount, 2),
                "new_amount": round(new_amount, 2),
                "message": "目标充电量修改成功"
            }
    except Exception as e:
        return {"success": False, "message": f"修改充电量失败: {str(e)}"}


def Modify_Mode(car_id: str, new_mode: str) -> dict:
    """
    【组员A核心接口】：支持车主中途切换快慢充模式。
    正在充电的车辆会先结算当前片段，释放旧桩，再重新调度至新模式充电桩。
    """
    new_mode = new_mode.upper()
    if new_mode not in ('F', 'T'):
        return {"success": False, "message": "充电模式必须为 F(快充) 或 T(慢充)"}

    try:
        with transaction.atomic():
            try:
                car = CarState.objects.select_for_update().get(car_id=car_id)
            except CarState.DoesNotExist:
                return {"success": False, "message": f"车辆 {car_id} 不存在"}

            if car.status not in ('CHARGING', 'QUEUEING'):
                return {"success": False, "message": f"车辆状态 {car.status} 不允许切换模式"}

            if car.mode == new_mode:
                return {"success": True, "action": "NO_CHANGE", "message": f"当前已是{'快充' if new_mode == 'F' else '慢充'}模式"}

            old_mode = car.mode
            old_pile_id = car.pile.pile_id if car.pile else None

            if car.status == 'CHARGING':
                now_time = timezone.now()
                pile = car.pile
                if car.last_update_time and pile:
                    pile = ChargePile.objects.select_for_update().get(pile_id=pile.pile_id)
                    amt, c_fee, s_fee = calculate_phase_fee(car.last_update_time, now_time, car.mode)
                    actual_amt = min(amt, car.request_amount - car.charged_amount)
                    if actual_amt > 0:
                        ratio = actual_amt / amt if amt > 0 else 1.0
                        duration_minutes = (now_time - car.last_update_time).total_seconds() * TIME_SCALE / 60
                        BillRecord.objects.create(
                            car_id=car_id, pile_id=pile.pile_id, charge_amount=actual_amt,
                            start_time=car.last_update_time, end_time=now_time,
                            charge_duration_minutes=duration_minutes,
                            charge_fee=c_fee * ratio, service_fee=s_fee * ratio,
                            total_fee=(c_fee + s_fee) * ratio
                        )
                        car.charged_amount += actual_amt
                        car.total_fee += (c_fee + s_fee) * ratio
                        pile.total_charge_amount += actual_amt
                    if car.start_time:
                        dur = (now_time - car.start_time).total_seconds() * TIME_SCALE / 60
                        pile.total_charge_duration_minutes += dur
                    pile.total_charge_times += 1
                    pile.current_car_id = None
                    pile.status = 'IDLE'
                    pile.save()

                car.pile = None
                car.queue_index = 0
                car.mode = new_mode
                car.status = 'WAITING'
                car.last_update_time = None
                car.start_time = None
                car.save()

                if old_pile_id:
                    from charging_system.services.dispatch_service import time_slice_schedule
                    time_slice_schedule(old_pile_id)

            else:
                car.pile = None
                car.queue_index = 0
                car.mode = new_mode
                car.status = 'WAITING'
                car.save()

            from charging_system.services.dispatch_service import priority_schedule
            reschedule_result = priority_schedule(car_id)

            return {
                "success": True,
                "action": "MODE_SWITCHED",
                "car_id": car_id,
                "old_mode": old_mode,
                "new_mode": new_mode,
                "reschedule": reschedule_result,
                "message": f"模式已从{'快充' if old_mode == 'F' else '慢充'}切换至{'快充' if new_mode == 'F' else '慢充'}，已重新调度"
            }
    except Exception as e:
        return {"success": False, "message": f"切换充电模式失败: {str(e)}"}


def Query_Charging_State(car_id: str) -> dict:
    """
    【组员B负责接口】：车主客户端实时轮询查询当前车辆的充电状态、已充度数、实时产生费用。
    改动点：去掉了原本累赘的动态计算，直接秒级从物理数据库映射获取最安全、精准的数据。
    """
    try:
        # 实时计算当前瞬时产生的动态电量与费用，使前端大屏和App能够像加油表一样丝滑跳动
        with transaction.atomic():
            try:
                car = CarState.objects.select_for_update().get(car_id=car_id)
            except CarState.DoesNotExist:
                return {"success": False, "message": f"车辆 {car_id} 不存在"}

            # 如果处于正在充电状态，根据时间差动态预估当前秒级跳动的电量（提升用户体验展示）
            current_total_fee = car.total_fee
            display_charged = car.charged_amount
            
            if car.status == 'CHARGING' and car.last_update_time:
                now_time = timezone.now()
                amt, c_fee, s_fee = calculate_phase_fee(car.last_update_time, now_time, car.mode)
                actual_amt = min(amt, car.request_amount - car.charged_amount)
                if actual_amt > 0:
                    ratio = actual_amt / amt if amt > 0 else 1.0
                    display_charged += actual_amt
                    current_total_fee += (c_fee + s_fee) * ratio

            duration_minutes = 0.0
            if car.start_time:
                end = car.end_time or timezone.now()
                duration_minutes = max((end - car.start_time).total_seconds() * TIME_SCALE / 60, 0)

            return {
                "success": True,
                "car_id": car.car_id,
                "car_state": car.status,
                "pile_id": car.pile.pile_id if car.pile else None,
                "pile_state": car.pile.status if car.pile else None,
                "request_amount": round(car.request_amount, 2),
                "charged_amount": round(display_charged, 2),
                "remaining_amount": round(max(car.request_amount - display_charged, 0), 2),
                "charge_duration_minutes": round(duration_minutes, 1),
                "current_fee": round(current_total_fee, 2),
                "mode": car.mode,
            }
    except Exception as e:
        return {"success": False, "message": f"查询失败: {str(e)}"}

