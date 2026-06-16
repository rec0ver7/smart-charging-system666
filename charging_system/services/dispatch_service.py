from typing import List

from charging_system.services.car_service import (
    CARS,
    PILES,
    CAR_STATUS_FAULT_WAITING,
    CAR_STATUS_QUEUEING,
    PILE_STATUS_FAULT,
    PILE_STATUS_IDLE,
    PILE_STATUS_CHARGING,
    assign_car_to_pile,
    Start_Charging,
)


# 组长负责
def priority_schedule():
    pass


def time_slice_schedule():
    pass


# D 负责
def time_order_schedule():
    pass


def _normal_piles_for_mode(mode: str):
    """
    找到同类型、非故障充电桩。
    F 车只进快充桩，T 车只进慢充桩。
    """
    mode = mode.upper()
    return [
        pile for pile in PILES.values()
        if pile.mode == mode and pile.status != PILE_STATUS_FAULT
    ]


def _queue_length_score(pile) -> int:
    """
    用于故障重调度：优先选择负载最小的可用桩。
    当前正在充电的车算 1，后方队列每辆车算 1。
    """
    running = 1 if pile.current_car_id else 0
    return running + len(pile.queue)


def _reschedule_one_car(car_id: str) -> str:
    """
    将一辆受故障影响的车重新分配到其他正常桩。
    返回调度结果说明。
    """
    if car_id not in CARS:
        return f"{car_id}: car_not_found"

    car = CARS[car_id]
    candidates = _normal_piles_for_mode(car.mode)

    if not candidates:
        car.status = CAR_STATUS_FAULT_WAITING
        car.pile_id = None
        return f"{car_id}: no_available_pile, moved_to_fault_waiting"

    target = sorted(candidates, key=lambda p: (_queue_length_score(p), p.pile_id))[0]

    old_pile_id = car.pile_id
    car.status = CAR_STATUS_QUEUEING
    car.pile_id = None

    ok = assign_car_to_pile(car_id, target.pile_id)
    if not ok:
        car.status = CAR_STATUS_FAULT_WAITING
        car.pile_id = None
        return f"{car_id}: assign_failed, moved_to_fault_waiting"

    if target.status == PILE_STATUS_IDLE and target.current_car_id == car_id:
        Start_Charging(car_id)
        return f"{car_id}: moved_from_{old_pile_id}_to_{target.pile_id}_and_started"

    return f"{car_id}: moved_from_{old_pile_id}_to_{target.pile_id}_queue"


# B 负责
def handle_pile_fault(fault_pile_id):
    """
    组员B负责：充电桩突发故障恢复逻辑。

    功能：
    1. 立即锁定故障桩；
    2. 提取该桩当前正在充电的车辆和后方排队车辆；
    3. 清空故障桩；
    4. 把受影响车辆重新调度到其他正常工作桩；
    5. 无可用桩时，将车辆置为 FAULT_WAITING。
    """
    if fault_pile_id not in PILES:
        return {
            "success": False,
            "message": f"充电桩 {fault_pile_id} 不存在",
            "affected_cars": [],
            "actions": [],
        }

    fault_pile = PILES[fault_pile_id]

    affected_cars: List[str] = []
    if fault_pile.current_car_id:
        affected_cars.append(fault_pile.current_car_id)

    affected_cars.extend(list(fault_pile.queue))

    fault_pile.status = PILE_STATUS_FAULT
    fault_pile.current_car_id = None
    fault_pile.queue.clear()

    actions = []
    for car_id in affected_cars:
        if car_id in CARS:
            car = CARS[car_id]
            car.pile_id = None
            car.status = CAR_STATUS_FAULT_WAITING
            car.last_update_time = None
        actions.append(_reschedule_one_car(car_id))

    return {
        "success": True,
        "fault_pile_id": fault_pile_id,
        "affected_cars": affected_cars,
        "actions": actions,
    }