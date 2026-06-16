from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


FAST_RATE = 30.0       # 快充：30度/小时
TRICKLE_RATE = 10.0    # 慢充：10度/小时
SERVICE_FEE_RATE = 0.8 # 服务费：0.8元/度，按测试可再调

PILE_STATUS_IDLE = "IDLE"
PILE_STATUS_CHARGING = "CHARGING"
PILE_STATUS_FAULT = "FAULT"

CAR_STATUS_WAITING = "WAITING"
CAR_STATUS_QUEUEING = "QUEUEING"
CAR_STATUS_CHARGING = "CHARGING"
CAR_STATUS_FINISHED = "FINISHED"
CAR_STATUS_FAULT_WAITING = "FAULT_WAITING"


@dataclass
class CarState:
    car_id: str
    mode: str = "T"  # F=快充, T=慢充
    request_amount: float = 0.0
    charged_amount: float = 0.0
    status: str = CAR_STATUS_WAITING
    pile_id: Optional[str] = None
    request_time: datetime = field(default_factory=datetime.now)
    start_time: Optional[datetime] = None
    last_update_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_fee: float = 0.0


@dataclass
class PileState:
    pile_id: str
    mode: str
    status: str = PILE_STATUS_IDLE
    current_car_id: Optional[str] = None
    queue: List[str] = field(default_factory=list)
    total_charge_amount: float = 0.0
    total_charge_times: int = 0
    total_charge_duration_minutes: float = 0.0


@dataclass
class BillRecord:
    car_id: str
    pile_id: str
    charge_amount: float
    start_time: datetime
    end_time: datetime
    charge_duration_minutes: float
    charge_fee: float
    service_fee: float
    total_fee: float


CARS: Dict[str, CarState] = {}
PILES: Dict[str, PileState] = {
    "F1": PileState("F1", "F"),
    "F2": PileState("F2", "F"),
    "T1": PileState("T1", "T"),
    "T2": PileState("T2", "T"),
    "T3": PileState("T3", "T"),
}
BILLS: List[BillRecord] = []


def _now() -> datetime:
    return datetime.now()


def _rate_by_mode(mode: str) -> float:
    return FAST_RATE if mode.upper() == "F" else TRICKLE_RATE


def _fee_per_kwh(now_time: Optional[datetime] = None) -> float:
    """
    简化分时电价：
    10:00-15:00, 18:00-21:00：峰 1.0
    7:00-10:00, 15:00-18:00, 21:00-23:00：平 0.7
    其他：谷 0.4
    """
    now_time = now_time or _now()
    hour = now_time.hour

    if 10 <= hour < 15 or 18 <= hour < 21:
        return 1.0
    if 7 <= hour < 10 or 15 <= hour < 18 or 21 <= hour < 23:
        return 0.7
    return 0.4


def _calculate_amount(car: CarState, at_time: Optional[datetime] = None) -> float:
    if car.status != CAR_STATUS_CHARGING or car.last_update_time is None:
        return 0.0

    at_time = at_time or _now()
    minutes = max((at_time - car.last_update_time).total_seconds() / 60, 0)
    amount = _rate_by_mode(car.mode) * minutes / 60
    remain = max(car.request_amount - car.charged_amount, 0)
    return min(amount, remain)


def _refresh_car_charge(car_id: str, at_time: Optional[datetime] = None) -> CarState:
    if car_id not in CARS:
        raise ValueError(f"车辆 {car_id} 不存在")

    car = CARS[car_id]
    if car.status != CAR_STATUS_CHARGING:
        return car

    at_time = at_time or _now()
    delta_amount = _calculate_amount(car, at_time)
    car.charged_amount += delta_amount
    car.last_update_time = at_time

    unit_fee = _fee_per_kwh(at_time)
    car.total_fee += delta_amount * (unit_fee + SERVICE_FEE_RATE)

    if car.charged_amount >= car.request_amount:
        End_Charging(car_id, auto=True, at_time=at_time)

    return car


def register_or_update_car(car_id: str, mode: str, request_amount: float,
                           request_time: Optional[datetime] = None) -> CarState:
    """
    给组长的 E_chargingRequest 或本地测试用。
    如果组长已经有创建车辆逻辑，可以不调用这个函数。
    """
    car = CARS.get(car_id)
    if car is None:
        car = CarState(
            car_id=car_id,
            mode=mode.upper(),
            request_amount=float(request_amount),
            request_time=request_time or _now(),
        )
        CARS[car_id] = car
    else:
        car.mode = mode.upper()
        car.request_amount = float(request_amount)
    return car


def assign_car_to_pile(car_id: str, pile_id: str) -> bool:
    """
    给调度模块使用：把车分配到某个桩。
    若桩空闲，直接成为当前车；若桩正在充电，进入该桩后方队列。
    """
    if car_id not in CARS or pile_id not in PILES:
        return False

    car = CARS[car_id]
    pile = PILES[pile_id]

    car.pile_id = pile_id
    if pile.status == PILE_STATUS_IDLE:
        pile.current_car_id = car_id
        car.status = CAR_STATUS_QUEUEING
    elif pile.status == PILE_STATUS_CHARGING:
        if car_id not in pile.queue:
            pile.queue.append(car_id)
        car.status = CAR_STATUS_QUEUEING
    else:
        return False

    return True


def Start_Charging(car_id: str) -> int:
    """
    组员B负责：
    控制车辆正式进入充电区，修改车辆和充电桩状态。
    返回 1 表示成功，0 表示失败。
    """
    if car_id not in CARS:
        return 0

    car = CARS[car_id]
    if not car.pile_id or car.pile_id not in PILES:
        return 0

    pile = PILES[car.pile_id]
    if pile.status == PILE_STATUS_FAULT:
        return 0

    if pile.current_car_id not in (None, car_id):
        return 0

    if car.status == CAR_STATUS_CHARGING:
        return 1

    pile.current_car_id = car_id
    pile.status = PILE_STATUS_CHARGING
    car.status = CAR_STATUS_CHARGING
    car.start_time = _now()
    car.last_update_time = car.start_time
    car.end_time = None

    if car_id in pile.queue:
        pile.queue.remove(car_id)

    return 1


def End_Charging(car_id: str, auto: bool = False,
                 at_time: Optional[datetime] = None) -> int:
    """
    组员B负责：
    用户主动结束或充满自动结束，锁定电量并生成账单。
    返回 1 表示成功，0 表示失败。
    """
    if car_id not in CARS:
        return 0

    car = CARS[car_id]
    if car.status != CAR_STATUS_CHARGING:
        return 0

    at_time = at_time or _now()

    if car.last_update_time is not None:
        delta_amount = _calculate_amount(car, at_time)
        car.charged_amount += delta_amount
        car.total_fee += delta_amount * (_fee_per_kwh(at_time) + SERVICE_FEE_RATE)

    car.charged_amount = min(car.charged_amount, car.request_amount)
    car.status = CAR_STATUS_FINISHED
    car.end_time = at_time

    pile = PILES.get(car.pile_id)
    if pile:
        duration_minutes = 0.0
        if car.start_time:
            duration_minutes = max((at_time - car.start_time).total_seconds() / 60, 0)

        pile.total_charge_amount += car.charged_amount
        pile.total_charge_duration_minutes += duration_minutes
        pile.total_charge_times += 1
        pile.current_car_id = None
        pile.status = PILE_STATUS_IDLE

        BILLS.append(BillRecord(
            car_id=car.car_id,
            pile_id=pile.pile_id,
            charge_amount=round(car.charged_amount, 2),
            start_time=car.start_time or at_time,
            end_time=at_time,
            charge_duration_minutes=round(duration_minutes, 2),
            charge_fee=round(car.charged_amount * _fee_per_kwh(at_time), 2),
            service_fee=round(car.charged_amount * SERVICE_FEE_RATE, 2),
            total_fee=round(car.total_fee, 2),
        ))

        if pile.queue:
            next_car_id = pile.queue.pop(0)
            next_car = CARS[next_car_id]
            next_car.pile_id = pile.pile_id
            pile.current_car_id = next_car_id
            Start_Charging(next_car_id)

    return 1


def Query_Charging_State(car_id: str) -> dict:
    """
    组员B负责：
    实时计算并返回当前已充电量、已产生费用、车辆状态等。
    """
    if car_id not in CARS:
        return {
            "success": False,
            "message": f"车辆 {car_id} 不存在",
        }

    car = _refresh_car_charge(car_id)
    pile = PILES.get(car.pile_id) if car.pile_id else None

    duration_minutes = 0.0
    if car.start_time:
        end = car.end_time or _now()
        duration_minutes = max((end - car.start_time).total_seconds() / 60, 0)

    return {
        "success": True,
        "car_id": car.car_id,
        "car_state": car.status,
        "pile_id": car.pile_id,
        "pile_state": pile.status if pile else None,
        "request_amount": round(car.request_amount, 2),
        "charged_amount": round(car.charged_amount, 2),
        "remaining_amount": round(max(car.request_amount - car.charged_amount, 0), 2),
        "charge_duration_minutes": round(duration_minutes, 2),
        "current_fee": round(car.total_fee, 2),
        "mode": car.mode,
    }


def get_system_snapshot() -> dict:
    """
    本地调试/验收展示用。
    """
    return {
        "cars": {cid: car.__dict__.copy() for cid, car in CARS.items()},
        "piles": {pid: pile.__dict__.copy() for pid, pile in PILES.items()},
        "bills": [bill.__dict__.copy() for bill in BILLS],
    }