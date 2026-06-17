from datetime import datetime
from django.db import transaction
from django.utils import timezone
from django.db.models import F
from charging_system.models import CarState, ChargePile, BillRecord
from charging_system.services.bill_service import calculate_phase_fee, TIME_SCALE

QUEUE_MAX_LIMIT = 4  # 桩后方专属队列最大车位数


# =========================================================================
# 组长负责：1. 核心请求接口与优先级入队调度算法
# =========================================================================
def E_chargingRequest(car_id: str, mode: str, request_amount: float) -> dict:
    """
    【组长负责接口】：用户端车辆在总等候区发起充电请求的入口
    """
    try:
        with transaction.atomic():
            car, created = CarState.objects.select_for_update().get_or_create(
                car_id=car_id,
                defaults={
                    'mode': mode.upper(),
                    'request_amount': request_amount,
                    'status': 'WAITING',
                    'total_fee': 0.0,
                    'charged_amount': 0.0
                }
            )
            if not created:
                if car.status in ['QUEUEING', 'CHARGING']:
                    return {"success": False, "message": "车辆已在队列中或正在充电，无法重复请求"}
                # 若此前是完结或故障状态，允许重置请求
                car.mode = mode.upper()
                car.request_amount = request_amount
                car.status = 'WAITING'
                car.pile = None
                car.queue_index = 0
                car.save()
                
        # 立即触发优先级调度算法叫号
        return priority_schedule(car_id)
    except Exception as e:
        return {"success": False, "message": f"充电请求发起失败: {str(e)}"}


def priority_schedule(car_id: str) -> dict:
    """
    【组长负责算法】：正常状态下的优先级贪心调度算法
    寻找当前对应模式下健康、排队加充电负载最小的充电桩。
    """
    try:
        with transaction.atomic():
            car = CarState.objects.select_for_update().get(car_id=car_id)
            candidates = ChargePile.objects.select_for_update().filter(
                mode=car.mode, status__in=['IDLE', 'CHARGING']
            )
            if not candidates.exists():
                car.status = 'FAULT_WAITING'
                car.save()
                return {"success": False, "message": "暂无对应模式的健康桩，进入故障等待区"}

            # 贪心评估负载最小的桩
            best_pile = None
            min_score = 99999
            for pile in candidates:
                q_count = pile.cars_in_queue.filter(status='QUEUEING').count()
                running_score = 1 if pile.status == 'CHARGING' else 0
                total_score = q_count + running_score
                
                if total_score < min_score:
                    min_score = total_score
                    best_pile = pile
                elif total_score == min_score:
                    if best_pile is None or pile.pile_id < best_pile.pile_id:
                        best_pile = pile

            # 校验4车位红线限制
            current_queue_len = best_pile.cars_in_queue.filter(status='QUEUEING').count()
            if current_queue_len >= QUEUE_MAX_LIMIT:
                car.status = 'WAITING'
                car.pile = None
                car.save()
                return {"success": True, "action": "WAIT", "message": "目标桩队列已满，保持在等候区排队"}

            car.pile = best_pile
            # 如果桩刚好空闲，直接触发充电
            if best_pile.status == 'IDLE' and current_queue_len == 0:
                car.status = 'CHARGING'
                car.start_time = timezone.now()
                car.last_update_time = timezone.now()
                car.queue_index = 0
                car.save()
                
                best_pile.status = 'CHARGING'
                best_pile.current_car_id = car_id
                best_pile.total_charge_times += 1
                best_pile.save()
                return {"success": True, "action": "STARTED", "pile_id": best_pile.pile_id}
            else:
                # 进入桩专属队列末尾
                car.status = 'QUEUEING'
                car.queue_index = current_queue_len + 1
                car.save()
                return {"success": True, "action": "QUEUED", "pile_id": best_pile.pile_id, "position": car.queue_index}
    except Exception as e:
        return {"success": False, "message": str(e)}


def time_slice_schedule(pile_id: str) -> dict:
    """
    【组长负责算法】：充电桩专属队列的多车时间片轮询切换机制
    打断当前充电车辆，产生一段详单，并将其塞到专属队列末尾，放第一位的车辆上桩。
    """
    try:
        with transaction.atomic():
            pile = ChargePile.objects.select_for_update().get(pile_id=pile_id)
            next_car = pile.cars_in_queue.filter(status='QUEUEING').order_by('queue_index', 'request_time').first()
            if not next_car:
                return {"success": True, "action": "KEEP", "message": "后方队列无车，无需切换"}
                
            old_car_id = pile.current_car_id
            now_time = timezone.now()
            
            if old_car_id:
                try:
                    old_car = CarState.objects.select_for_update().get(car_id=old_car_id)
                    if old_car.status == 'CHARGING':
                        # 结算当前这一时间片片段产生的费用与电量
                        amt, c_fee, s_fee = calculate_phase_fee(old_car.last_update_time, now_time, old_car.mode)
                        actual_amt = min(amt, old_car.request_amount - old_car.charged_amount)
                        
                        if actual_amt > 0:
                            # 比例缩放计算真实的费用片段
                            ratio = actual_amt / amt if amt > 0 else 1.0
                            BillRecord.objects.create(
                                car_id=old_car_id, pile_id=pile_id, charge_amount=actual_amt,
                                start_time=old_car.last_update_time, end_time=now_time,
                                charge_duration_minutes=(now_time - old_car.last_update_time).total_seconds() * 60 / 3600, # 配合模拟系数
                                charge_fee=c_fee * ratio, service_fee=s_fee * ratio, total_fee=(c_fee + s_fee) * ratio
                            )
                            old_car.charged_amount += actual_amt
                            old_car.total_fee += (c_fee + s_fee) * ratio
                        
                        # 挪到队尾
                        old_car.status = 'QUEUEING'
                        current_max_index = pile.cars_in_queue.filter(status='QUEUEING').count()
                        old_car.queue_index = current_max_index + 1
                        old_car.request_time = now_time
                        old_car.save()
                        
                        pile.total_charge_amount += actual_amt
                except CarState.DoesNotExist:
                    pass

            # 激活新一轮车辆
            next_car.status = 'CHARGING'
            next_car.start_time = next_car.start_time or now_time
            next_car.last_update_time = now_time
            next_car.queue_index = 0
            next_car.save()
            
            # 其他车辆顺位向前移动
            pile.cars_in_queue.filter(status='QUEUEING').exclude(car_id=old_car_id).update(queue_index=F('queue_index') - 1)
            
            pile.status = 'CHARGING'
            pile.current_car_id = next_car.car_id
            pile.total_charge_times += 1
            pile.save()
            return {"success": True, "action": "SWITCHED", "new_car": next_car.car_id}
    except Exception as e:
        return {"success": False, "message": str(e)}


# =========================================================================
# 组员 D 负责：2. 故障备用时序调度算法
# =========================================================================
def time_order_schedule() -> dict:
    """
    【组员D负责算法】：严格按照时间戳公平原则，从“总等候区”调车填补进入“充电桩专属排队区”
    """
    try:
        with transaction.atomic():
            # 筛选出总等候区排队的车辆，严格按发起时间戳升序排序（最早的先调入）
            waiting_cars = CarState.objects.select_for_update().filter(status='WAITING').order_by('request_time')
            dispatched_count = 0
            
            for car in waiting_cars:
                # 为该车重新寻找当前负载最低且专属队列未满（<4）的充电桩
                candidates = ChargePile.objects.select_for_update().filter(mode=car.mode, status__in=['IDLE', 'CHARGING'])
                best_pile = None
                min_queue = QUEUE_MAX_LIMIT
                
                for pile in candidates:
                    q_len = pile.cars_in_queue.filter(status='QUEUEING').count()
                    if q_len < min_queue:
                        min_queue = q_len
                        best_pile = pile
                
                if best_pile:
                    # 调入该充电桩队列
                    car.pile = best_pile
                    if best_pile.status == 'IDLE' and min_queue == 0:
                        car.status = 'CHARGING'
                        car.start_time = timezone.now()
                        car.last_update_time = timezone.now()
                        car.queue_index = 0
                        best_pile.status = 'CHARGING'
                        best_pile.current_car_id = car.car_id
                        best_pile.save()
                    else:
                        car.status = 'QUEUEING'
                        car.queue_index = min_queue + 1
                    car.save()
                    dispatched_count += 1
                    
            return {"success": True, "message": f"时序公平调度扫描结束，共调入 {dispatched_count} 辆车进入充电区"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# =========================================================================
# 组员 B 负责：3. 突发故障重调度恢复算法
# =========================================================================
def handle_pile_fault(fault_pile_id: str) -> dict:
    """
    【组员B负责算法】：充电桩突发故障处理逻辑（已从原本的内存字典重构为高并发安全ORM版本）
    功能：锁定故障桩，将其所有的充电车与排队车强行抽出，并进行重调度或打回故障等待区。
    """
    try:
        with transaction.atomic():
            try:
                fault_pile = ChargePile.objects.select_for_update().get(pile_id=fault_pile_id)
            except ChargePile.DoesNotExist:
                return {"success": False, "message": "该故障充电桩不存在"}
                
            fault_pile.status = 'FAULT'
            old_car_id = fault_pile.current_car_id
            fault_pile.current_car_id = None
            fault_pile.save()
            
            affected_car_ids = []
            # 1. 提取正在充电的车进行中途费用结算
            if old_car_id:
                affected_car_ids.append(old_car_id)
                try:
                    old_car = CarState.objects.select_for_update().get(car_id=old_car_id)
                    if old_car.status == 'CHARGING':
                        now_time = timezone.now()
                        amt, c_fee, s_fee = calculate_phase_fee(old_car.last_update_time, now_time, old_car.mode)
                        actual_amt = min(amt, old_car.request_amount - old_car.charged_amount)
                        if actual_amt > 0:
                            ratio = actual_amt / amt if amt > 0 else 1.0
                            BillRecord.objects.create(
                                car_id=old_car_id, pile_id=fault_pile_id, charge_amount=actual_amt,
                                start_time=old_car.last_update_time, end_time=now_time,
                                charge_duration_minutes=(now_time - old_car.last_update_time).total_seconds() * TIME_SCALE / 60,
                                charge_fee=c_fee * ratio, service_fee=s_fee * ratio, total_fee=(c_fee + s_fee) * ratio
                            )
                            old_car.charged_amount += actual_amt
                            old_car.total_fee += (c_fee + s_fee) * ratio
                        old_car.status = 'FAULT_WAITING'
                        old_car.pile = None
                        old_car.queue_index = 0
                        old_car.save()
                except CarState.DoesNotExist:
                    pass
            
            # 2. 提取排队车辆
            queue_cars = fault_pile.cars_in_queue.filter(status='QUEUEING').order_by('queue_index')
            for car in queue_cars:
                affected_car_ids.append(car.car_id)
                car.status = 'FAULT_WAITING'
                car.pile = None
                car.queue_index = 0
                car.save()
            
            # 3. 逐一重调度受灾车辆到其他健康充电桩上
            resched_actions = []
            for cid in affected_car_ids:
                res = priority_schedule(cid)
                if res.get('success') and res.get('action') in ['STARTED', 'QUEUED']:
                    resched_actions.append(f"车辆 {cid} 成功重调度至新桩 {res.get('pile_id')}")
                else:
                    resched_actions.append(f"车辆 {cid} 暂无可去位置，滞留在故障再调度等待区")
                    
            return {
                "success": True,
                "pile_id": fault_pile_id,
                "status": "LOCKED_FAULT",
                "affected_cars": affected_car_ids,
                "reschedule_log": resched_actions
            }
    except Exception as e:
        return {"success": False, "message": f"突发故障重调度逻辑异常: {str(e)}"}