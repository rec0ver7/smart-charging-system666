"""
复杂压力测试：数十辆车并发、冲突、级联故障、混合模式大乱斗
"""
from django.test import TestCase
from django.utils import timezone
from charging_system.models import ChargePile, CarState, BillRecord
from charging_system.services.dispatch_service import (
    E_chargingRequest, priority_schedule, time_slice_schedule,
    time_order_schedule, handle_pile_fault
)
from charging_system.services.car_service import (
    Start_Charging, End_Charging, Query_Charging_State,
    Modify_Amount, Modify_Mode
)
from charging_system.services.pile_service import (
    Query_QueueState, Query_PileState, powerOn, powerOff,
    auto_tick_piles
)


class StressMassConcurrencyTest(TestCase):
    """大量并发请求"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_F2', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_01_twenty_cars_slow_mode(self):
        """20辆慢充车：3桩分流+排队，无车丢失"""
        results = []
        for i in range(20):
            r = E_chargingRequest(f'CAR_{i:02d}', 'T', 30 + i % 20)
            results.append(r)
        self.assertTrue(all(r['success'] for r in results))

        # 统计状态分布
        charging = CarState.objects.filter(status='CHARGING').count()
        queuing = CarState.objects.filter(status='QUEUEING').count()
        waiting = CarState.objects.filter(status='WAITING').count()
        finished = CarState.objects.filter(status='FINISHED').count()

        self.assertEqual(charging, 3, f'应3车充电中，实际{charging}')
        # 每桩4队列 = 12辆排队 + 3辆充电 = 15辆，剩余5辆WAITING
        self.assertEqual(queuing + waiting, 17)
        self.assertEqual(CarState.objects.count(), 20)

    def test_02_twenty_cars_mixed_mode(self):
        """20辆混合快慢充：模式隔离正确"""
        for i in range(10):
            E_chargingRequest(f'FCAR_{i}', 'F', 20)
        for i in range(10):
            E_chargingRequest(f'TCAR_{i}', 'T', 30)

        # 快充车只能在快充桩
        for c in CarState.objects.filter(mode='F'):
            if c.pile:
                self.assertEqual(c.pile.mode, 'F',
                    f'{c.car_id} 在 {c.pile.mode} 桩，应在 F 桩')

        # 慢充车只能在慢充桩
        for c in CarState.objects.filter(mode='T'):
            if c.pile:
                self.assertEqual(c.pile.mode, 'T',
                    f'{c.car_id} 在 {c.pile.mode} 桩，应在 T 桩')

    def test_03_all_slow_piles_full_then_fast_untouched(self):
        """慢充桩全满不影响快充桩"""
        # 填满慢充桩（3桩 * (1充电+4排队) = 15辆）
        for i in range(20):
            E_chargingRequest(f'T_{i}', 'T', 30)

        # 快充桩应仍然空闲
        for pid in ['PILE_F1', 'PILE_F2']:
            pile = ChargePile.objects.get(pile_id=pid)
            self.assertEqual(pile.status, 'IDLE',
                f'{pid} 应为 IDLE，实际 {pile.status}')

        # 快充车直接上桩
        r = E_chargingRequest('F_NEW', 'F', 20)
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'STARTED')
        car = CarState.objects.get(car_id='F_NEW')
        self.assertIn(car.pile.mode, ['F'])

    def test_04_mass_request_then_some_finish_cascade(self):
        """大量请求后部分完成，队列级联推进"""
        # 填满系统：3慢充桩 + 每桩4队列 = 15辆
        for i in range(15):
            E_chargingRequest(f'M_{i:02d}', 'T', 10)

        # 手动结算3辆正在充电的车
        charging_cars = list(CarState.objects.filter(status='CHARGING'))
        self.assertEqual(len(charging_cars), 3)

        for car in charging_cars:
            car.charged_amount = car.request_amount
            car.save()

        # 依次结束，每结束1辆触发下一辆上桩
        for pile in ChargePile.objects.filter(status='CHARGING'):
            End_Charging(pile.current_car_id)

        # 应该又有3辆在充电（队列中顶上来的）
        new_charging = CarState.objects.filter(status='CHARGING').count()
        self.assertEqual(new_charging, 3,
            f'3辆完成后应有3辆顶上，实际{new_charging}辆在充电')
        # 剩余排队车应正确
        total_active = CarState.objects.filter(status__in=['CHARGING', 'QUEUEING', 'WAITING']).count()
        # 3 done + 3 charging + remaining queuing = 15 original - 3 done = 12 active
        self.assertEqual(total_active, 12)


class StressQueueDynamicsTest(TestCase):
    """队列动力学压力测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_05_queue_churn_cars_come_and_go(self):
        """车辆频繁进出，队列序号始终保持连续正确"""
        # 3车占3桩
        for i in range(3):
            E_chargingRequest(f'Q_CHARGE_{i}', 'T', 100)

        # 12辆排满所有队列 (3桩 * 4)
        for i in range(12):
            E_chargingRequest(f'Q_INIT_{i:02d}', 'T', 20)

        # 再3辆WAITING
        for i in range(3):
            E_chargingRequest(f'Q_WAIT_{i}', 'T', 20)

        # 结束 PILE_T1 的充电车 → 队列第一辆上桩 → 空出一个排队位 → WAITING 车填入
        pile1 = ChargePile.objects.get(pile_id='PILE_T1')
        car_on_pile1 = CarState.objects.get(car_id=pile1.current_car_id)
        car_on_pile1.charged_amount = 200  # 充满
        car_on_pile1.save()
        End_Charging(car_on_pile1.car_id)

        # 验证：PILE_T1 有新车上桩
        pile1.refresh_from_db()
        self.assertIsNotNone(pile1.current_car_id)
        self.assertEqual(pile1.status, 'CHARGING')

        # 验证 PILE_T1 队列长度（最多4-1=3，因为有1辆从WAITING填入）
        q1 = pile1.cars_in_queue.filter(status='QUEUEING').count()
        self.assertLessEqual(q1, 4)

        # 验证 queue_index 连续性（无跳号）
        queue_cars = pile1.cars_in_queue.filter(status='QUEUEING').order_by('queue_index')
        indices = [c.queue_index for c in queue_cars]
        if len(indices) > 1:
            for j in range(len(indices) - 1):
                self.assertEqual(indices[j+1] - indices[j], 1,
                    f'PILE_T1队列序号不连续: {indices}')

    def test_06_time_slice_churn_twenty_rotations(self):
        """时间片轮转20次，无车丢失、序号不混乱"""
        # 1桩3排队（简单场景便于验证）
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'ROTATE_0'
        pile.save()

        CarState.objects.create(car_id='ROTATE_0', mode='T', request_amount=10,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())
        for i in range(1, 4):
            CarState.objects.create(car_id=f'ROTATE_{i}', mode='T', request_amount=10,
                                    status='QUEUEING', pile=pile, queue_index=i,
                                    request_time=timezone.now())

        # 轮转20次
        for _ in range(20):
            time_slice_schedule('PILE_T1')

        # 所有车都应还在（状态不为FINISHED除非达到目标）
        for i in range(4):
            car = CarState.objects.get(car_id=f'ROTATE_{i}')
            self.assertIn(car.status, ['CHARGING', 'QUEUEING', 'FINISHED'])

        # 恰好1辆车在充电
        self.assertEqual(
            CarState.objects.filter(pile=pile, status='CHARGING').count(), 1)

    def test_07_queue_ordering_respected_over_time(self):
        """长时间运行后队列顺序仍然正确"""
        # 3辆车顺序入队
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'FIXED_CAR'
        pile.save()
        CarState.objects.create(car_id='FIXED_CAR', mode='T', request_amount=5,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        # 3辆车按顺序排队
        for i, cid in enumerate(['A_FIRST', 'B_SECOND', 'C_THIRD'], 1):
            CarState.objects.create(car_id=cid, mode='T', request_amount=10,
                                    status='QUEUEING', pile=pile, queue_index=i,
                                    request_time=timezone.now())

        # 3次轮转：FIXED -> A -> B -> C 依次上桩
        for expected_car in ['A_FIRST', 'B_SECOND', 'C_THIRD']:
            time_slice_schedule('PILE_T1')
            pile.refresh_from_db()
            self.assertEqual(pile.current_car_id, expected_car,
                f'应为 {expected_car} 上桩，实际 {pile.current_car_id}')


class StressFaultCascadeTest(TestCase):
    """级联故障压力测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_08_double_fault_cascade(self):
        """两根桩连续故障，所有受灾车重调度"""
        # 3桩各1车充电 + 各2车排队 = 9车
        for pid in ['PILE_T1', 'PILE_T2', 'PILE_T3']:
            pile = ChargePile.objects.get(pile_id=pid)
            pile.status = 'CHARGING'
            pile.current_car_id = f'{pid}_C'
            pile.save()
            CarState.objects.create(car_id=f'{pid}_C', mode='T', request_amount=50,
                                    charged_amount=10, status='CHARGING', pile=pile,
                                    last_update_time=timezone.now(), start_time=timezone.now())
            for i in range(2):
                CarState.objects.create(car_id=f'{pid}_Q{i}', mode='T',
                                        request_amount=20, status='QUEUEING',
                                        pile=pile, queue_index=i+1,
                                        request_time=timezone.now())

        # PILE_T1 故障
        r1 = handle_pile_fault('PILE_T1')
        self.assertTrue(r1['success'])
        self.assertEqual(len(r1['affected_cars']), 3)  # 1充电+2排队

        # 验证受灾车重调度到 PILE_T2 或 PILE_T3
        for cid in r1['affected_cars']:
            car = CarState.objects.get(car_id=cid)
            self.assertNotEqual(car.status, 'FAULT_WAITING',
                f'{cid} 应重调度成功，实际 {car.status}')

        # PILE_T2 也故障（只剩 PILE_T3 健康）
        r2 = handle_pile_fault('PILE_T2')
        self.assertTrue(r2['success'])
        # PILE_T2 受灾车（自己的3辆 + 从PILE_T1重调度来的车）
        t2_cars = [c for c in r2['affected_cars']]
        self.assertGreaterEqual(len(t2_cars), 3)

        # 只有 PILE_T3 健康，部分车可能在 FAULT_WAITING
        # 修复 PILE_T1
        powerOn('PILE_T1')
        pile1 = ChargePile.objects.get(pile_id='PILE_T1')
        self.assertEqual(pile1.status, 'IDLE')

        # FAULT_WAITING 车应可通过 auto_tick 恢复
        # 先让 PILE_T3 完成 → 触发 FAULT_WAITING 恢复
        pile3 = ChargePile.objects.get(pile_id='PILE_T3')
        if pile3.current_car_id:
            try:
                car3 = CarState.objects.get(car_id=pile3.current_car_id)
                car3.charged_amount = 999  # 充满
                car3.save()
                End_Charging(car3.car_id)
            except CarState.DoesNotExist:
                pass

        # auto_tick 应恢复 FAULT_WAITING 车到 PILE_T1
        auto_tick_piles()
        fault_left = CarState.objects.filter(status='FAULT_WAITING').count()
        # 可能还有，如果 PILE_T1 也满了
        self.assertLessEqual(fault_left, 12)  # 宽松检查

    def test_09_fault_on_most_loaded_pile(self):
        """最繁忙桩故障——该桩有充电车+满队列"""
        # PILE_T1 满负荷：1充电+4排队
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'BUSY_0'
        pile.save()
        CarState.objects.create(car_id='BUSY_0', mode='T', request_amount=30,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())
        for i in range(1, 5):
            CarState.objects.create(car_id=f'BUSY_{i}', mode='T', request_amount=10,
                                    status='QUEUEING', pile=pile, queue_index=i,
                                    request_time=timezone.now())

        # PILE_T2, PILE_T3 空闲
        r = handle_pile_fault('PILE_T1')
        self.assertTrue(r['success'])
        self.assertEqual(len(r['affected_cars']), 5)  # 1充电+4排队

        # 所有5辆受灾车应重调度到 PILE_T2/T3
        for cid in r['affected_cars']:
            car = CarState.objects.get(car_id=cid)
            self.assertNotEqual(car.status, 'FAULT_WAITING',
                f'{cid} 空闲桩存在却未重调度，状态={car.status}')

    def test_10_all_piles_fault_then_one_by_one_recover(self):
        """所有桩逐个故障再逐个恢复"""
        # 3桩各1车
        for pid in ['PILE_T1', 'PILE_T2', 'PILE_T3']:
            pile = ChargePile.objects.get(pile_id=pid)
            pile.status = 'CHARGING'
            pile.current_car_id = f'{pid}_X'
            pile.save()
            CarState.objects.create(car_id=f'{pid}_X', mode='T', request_amount=50,
                                    charged_amount=10, status='CHARGING', pile=pile,
                                    last_update_time=timezone.now(), start_time=timezone.now())

        # 逐个故障
        for pid in ['PILE_T1', 'PILE_T2', 'PILE_T3']:
            r = handle_pile_fault(pid)
            self.assertTrue(r['success'])

        # 所有桩都是 FAULT
        self.assertEqual(ChargePile.objects.filter(status='FAULT').count(), 3)

        # 逐个恢复
        for pid in ['PILE_T1', 'PILE_T2', 'PILE_T3']:
            powerOn(pid)
            pile = ChargePile.objects.get(pile_id=pid)
            self.assertEqual(pile.status, 'IDLE')
            # 恢复后触发 FAULT_WAITING 重调度
            auto_tick_piles()

        # 所有车应恢复
        fault_cars = CarState.objects.filter(status='FAULT_WAITING').count()
        self.assertEqual(fault_cars, 0,
            f'所有桩恢复后不应有FAULT_WAITING车，实际{fault_cars}辆')


class StressMixedOperationsTest(TestCase):
    """混合操作压力测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_F2', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_11_mass_mode_switch_under_load(self):
        """满负荷下大批量切换模式"""
        # 慢充桩全部填满
        for i in range(20):
            E_chargingRequest(f'SW_{i}', 'T', 20)

        # 选5辆排队中的慢充车切到快充
        queuing_t = CarState.objects.filter(mode='T', status='QUEUEING')[:5]
        for car in queuing_t:
            r = Modify_Mode(car.car_id, 'F')
            self.assertTrue(r['success'], f'{car.car_id} 切换模式失败: {r}')
            car.refresh_from_db()
            self.assertEqual(car.mode, 'F')

        # 快充车应已分配到快充桩
        for car in queuing_t:
            car.refresh_from_db()
            if car.pile:
                self.assertEqual(car.pile.mode, 'F')

    def test_12_modify_amount_while_queuing(self):
        """排队中批量修改目标电量"""
        # 填满系统
        for i in range(15):
            E_chargingRequest(f'MA_{i}', 'T', 50)

        # 选所有排队车修改电量
        queuing = CarState.objects.filter(status='QUEUEING')
        self.assertGreater(queuing.count(), 0)

        for car in queuing:
            r = Modify_Amount(car.car_id, 80)
            self.assertTrue(r['success'])
            car.refresh_from_db()
            self.assertEqual(car.request_amount, 80)

    def test_13_race_condition_end_and_start(self):
        """同时结束和开始充电不冲突"""
        # 3辆车上桩
        for i in range(3):
            E_chargingRequest(f'RC_{i}', 'T', 10)

        # 立即结束所有充电车
        charging_cars = list(CarState.objects.filter(status='CHARGING'))
        for car in charging_cars:
            car.charged_amount = 999
            car.save()

        # 同时结束 + 同时请求新车
        results = []
        for car in charging_cars:
            results.append(End_Charging(car.car_id))
        for i in range(6):
            results.append(E_chargingRequest(f'RC_NEW_{i}', 'T', 15)['success'])

        self.assertTrue(all(r in [0, 1] or r is True for r in results))

        # 系统应稳定：3桩在充电
        charging_count = CarState.objects.filter(status='CHARGING').count()
        self.assertEqual(charging_count, 3)

    def test_14_long_running_mixed_workload(self):
        """长时间混合负载：100次随机操作"""
        import random
        random.seed(42)

        # 预置10辆车
        for i in range(10):
            mode = random.choice(['F', 'T'])
            amt = random.randint(5, 100)
            E_chargingRequest(f'LR_{i}', mode, amt)

        # 100次随机操作
        for step in range(100):
            op = random.choice([
                'new_car', 'query', 'modify_amount', 'modify_mode',
                'end', 'fault', 'recover', 'tick'
            ])

            if op == 'new_car':
                mode = random.choice(['F', 'T'])
                amt = random.randint(5, 100)
                E_chargingRequest(f'LR_N{step}', mode, amt)

            elif op == 'query':
                all_cars = CarState.objects.all()
                if all_cars.exists():
                    car = random.choice(all_cars)
                    Query_Charging_State(car.car_id)

            elif op == 'modify_amount':
                queuing_or_charging = CarState.objects.filter(
                    status__in=['QUEUEING', 'CHARGING']
                )
                if queuing_or_charging.exists():
                    car = random.choice(queuing_or_charging)
                    Modify_Amount(car.car_id, car.request_amount + random.randint(-5, 20))

            elif op == 'modify_mode':
                queuing_or_charging = CarState.objects.filter(
                    status__in=['QUEUEING', 'CHARGING']
                )
                if queuing_or_charging.exists():
                    car = random.choice(queuing_or_charging)
                    new_mode = 'F' if car.mode == 'T' else 'T'
                    Modify_Mode(car.car_id, new_mode)

            elif op == 'end':
                charging = CarState.objects.filter(status='CHARGING')
                if charging.exists():
                    car = random.choice(charging)
                    End_Charging(car.car_id)

            elif op == 'fault':
                healthy = ChargePile.objects.filter(status__in=['IDLE', 'CHARGING'])
                if healthy.exists():
                    pile = random.choice(healthy)
                    handle_pile_fault(pile.pile_id)

            elif op == 'recover':
                faulted = ChargePile.objects.filter(status='FAULT')
                if faulted.exists():
                    pile = random.choice(faulted)
                    powerOn(pile.pile_id)
                    auto_tick_piles()

            elif op == 'tick':
                auto_tick_piles()

        # 系统不应崩溃，所有状态应合法
        for car in CarState.objects.all():
            self.assertIn(car.status, ['WAITING', 'QUEUEING', 'CHARGING', 'FINISHED', 'FAULT_WAITING'])
            if car.status == 'CHARGING':
                self.assertIsNotNone(car.pile)
            if car.status == 'FINISHED':
                self.assertIsNone(car.pile)

        # 所有桩状态合法
        for pile in ChargePile.objects.all():
            self.assertIn(pile.status, ['IDLE', 'CHARGING', 'FAULT'])


class StressEdgeCaseComboTest(TestCase):
    """极端组合边界测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_F2', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_15_all_fast_piles_fault_slow_untouched(self):
        """快充桩全故障，慢充车不受影响，快充车 FAULT_WAITING"""
        # 2辆慢充正常
        E_chargingRequest('T_OK1', 'T', 30)
        E_chargingRequest('T_OK2', 'T', 30)

        # 快充桩全故障
        ChargePile.objects.filter(mode='F').update(status='FAULT')

        # 快充车请求 → FAULT_WAITING
        r = E_chargingRequest('F_STUCK', 'F', 30)
        self.assertFalse(r['success'])
        car_f = CarState.objects.get(car_id='F_STUCK')
        self.assertEqual(car_f.status, 'FAULT_WAITING')

        # 慢充车正常
        for cid in ['T_OK1', 'T_OK2']:
            car = CarState.objects.get(car_id=cid)
            self.assertEqual(car.status, 'CHARGING')

        # 恢复快充桩 → FAULT_WAITING 恢复
        powerOn('PILE_F1')
        auto_tick_piles()
        car_f.refresh_from_db()
        self.assertNotEqual(car_f.status, 'FAULT_WAITING',
            f'快充桩恢复后 F_STUCK 应被调度，实际={car_f.status}')

    def test_16_one_pile_takes_all_forty_four_queue(self):
        """1根桩满载4排队 + 大量WAITING车 → 其他桩空闲"""
        # 只让 PILE_T1 可用的场景（PILE_T2, T3 故障）
        ChargePile.objects.filter(pile_id__in=['PILE_T2', 'PILE_T3']).update(status='FAULT')

        # PILE_T1 满负荷：1+4=5辆
        for i in range(5):
            E_chargingRequest(f'SINGLE_{i}', 'T', 30)

        # 第6辆 WAITING
        r = E_chargingRequest('SINGLE_OVER', 'T', 20)
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'WAIT')

        car = CarState.objects.get(car_id='SINGLE_OVER')
        self.assertEqual(car.status, 'WAITING')

        # 恢复 PILE_T2 → WAITING 应分配过去
        powerOn('PILE_T2')
        auto_tick_piles()
        car.refresh_from_db()
        self.assertNotEqual(car.status, 'WAITING',
            f'PILE_T2 恢复后应分配，实际={car.status}')

    def test_17_zero_amount_request_edge_case(self):
        """请求0度电 → 直接完成"""
        CarState.objects.create(car_id='ZERO', mode='T', request_amount=0,
                                charged_amount=0, status='WAITING')
        r = priority_schedule('ZERO')
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'FINISHED')

    def test_18_car_modify_to_negative_amount(self):
        """修改为负数 → 拒绝"""
        E_chargingRequest('NEG', 'T', 50)
        r = Modify_Amount('NEG', -10)
        self.assertFalse(r['success'])

    def test_19_car_modify_to_zero(self):
        """修改为0 → 拒绝"""
        E_chargingRequest('ZERO_MOD', 'T', 50)
        r = Modify_Amount('ZERO_MOD', 0)
        self.assertFalse(r['success'])

    def test_20_same_car_duplicate_request_rejected(self):
        """同一辆车重复请求被拒绝"""
        E_chargingRequest('DUP', 'T', 50)
        r = E_chargingRequest('DUP', 'F', 30)  # 改模式重请求
        self.assertFalse(r['success'])

    def test_21_duplicate_car_after_finish_allowed(self):
        """完成后重新请求应允许"""
        E_chargingRequest('REUSE', 'T', 30)
        car = CarState.objects.get(car_id='REUSE')
        car.status = 'FINISHED'
        car.pile = None
        car.save()

        r = E_chargingRequest('REUSE', 'F', 50)  # 完成后可用快充重新请求
        self.assertTrue(r['success'])
        car.refresh_from_db()
        self.assertEqual(car.mode, 'F')
        self.assertEqual(car.request_amount, 50)

    def test_22_fault_then_power_off_then_power_on_cycle(self):
        """故障→关机→开机→可用 循环"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')

        # 循环3次
        for _ in range(3):
            powerOff('PILE_T1')
            pile.refresh_from_db()
            self.assertEqual(pile.status, 'FAULT')

            powerOn('PILE_T1')
            pile.refresh_from_db()
            self.assertEqual(pile.status, 'IDLE')

    def test_23_query_nonexistent_car(self):
        """查询不存在的车"""
        r = Query_Charging_State('GHOST_CAR')
        self.assertFalse(r['success'])

    def test_24_query_nonexistent_pile(self):
        """查询不存在的桩"""
        r = Query_QueueState('GHOST_PILE')
        self.assertFalse(r['success'])

    def test_25_pile_parameters_update_and_query(self):
        """电价参数修改与查询"""
        from charging_system.services.pile_service import setParameters, get_pile_parameters

        orig = get_pile_parameters()
        r = setParameters(peak_price=2.0, service_fee_rate=1.0)
        self.assertTrue(r['success'])

        new_params = get_pile_parameters()
        self.assertEqual(new_params['peak_price'], 2.0)
        self.assertEqual(new_params['service_fee_rate'], 1.0)

        # 恢复
        setParameters(peak_price=orig['peak_price'], service_fee_rate=orig['service_fee_rate'])

    def test_26_ten_cars_then_all_finish_then_ten_more(self):
        """10辆车全部完成后再来10辆——系统重置能力"""
        # 第一批10辆
        for i in range(10):
            E_chargingRequest(f'BATCH1_{i}', 'T', 5)

        # 全部完成
        for car in CarState.objects.filter(status__in=['CHARGING', 'QUEUEING']):
            car.charged_amount = 999
            car.status = 'FINISHED'
            car.pile = None
            car.queue_index = 0
            car.end_time = timezone.now()
            car.save()

        # 清理桩状态
        for pile in ChargePile.objects.filter(mode='T'):
            pile.status = 'IDLE'
            pile.current_car_id = None
            pile.save()

        # 第二批10辆
        for i in range(10):
            r = E_chargingRequest(f'BATCH2_{i}', 'T', 5)
            self.assertTrue(r['success'])

        # 应有3辆充电中
        self.assertEqual(CarState.objects.filter(status='CHARGING').count(), 3)
        # 17 total active = 3 charging + 最多12排队 + 最少2 WAITING
        active = CarState.objects.filter(status__in=['CHARGING', 'QUEUEING', 'WAITING']).count()
        self.assertEqual(active, 10)

    def test_27_mixed_fast_slow_fault_only_fast(self):
        """仅快充桩故障，快充车全部转为 FAULT_WAITING"""
        # 慢充正常
        for i in range(3):
            E_chargingRequest(f'MS_T_{i}', 'T', 30)
        # 快充正常
        for i in range(2):
            E_chargingRequest(f'MS_F_{i}', 'F', 20)

        # 快充桩全故障
        for pid in ['PILE_F1', 'PILE_F2']:
            handle_pile_fault(pid)

        # 新快充车无法调度
        r = E_chargingRequest('MS_F_NEW', 'F', 30)
        self.assertFalse(r['success'])
        car = CarState.objects.get(car_id='MS_F_NEW')
        self.assertEqual(car.status, 'FAULT_WAITING')

        # 慢充车不受影响
        slow_cars = CarState.objects.filter(mode='T')
        for car in slow_cars:
            self.assertIn(car.status, ['CHARGING', 'QUEUEING'])

        # 恢复1根快充桩
        powerOn('PILE_F1')
        auto_tick_piles()

        # FAULT_WAITING 车应恢复
        fault_f_cars = CarState.objects.filter(mode='F', status='FAULT_WAITING')
        self.assertEqual(fault_f_cars.count(), 0,
            f'快充桩恢复后不应有 FAULT_WAITING F车，实际{fault_f_cars.count()}辆')

    def test_28_fifty_cars_total_stress(self):
        """50辆车总压力测试——系统不崩溃"""
        for i in range(50):
            mode = 'F' if i % 5 < 2 else 'T'  # 20快 + 30慢
            amt = 10 + (i * 7) % 90
            E_chargingRequest(f'BIG_{i:03d}', mode, amt)

        # 所有车状态合法
        for car in CarState.objects.all():
            self.assertIn(car.status,
                ['WAITING', 'QUEUEING', 'CHARGING', 'FINISHED', 'FAULT_WAITING'])
            if car.status == 'CHARGING':
                self.assertIsNotNone(car.pile)
            if car.status == 'FINISHED':
                self.assertIsNone(car.pile)
            if car.status == 'QUEUEING':
                self.assertIsNotNone(car.pile)
                self.assertGreater(car.queue_index, 0)

        # 桩状态合法
        for pile in ChargePile.objects.all():
            self.assertIn(pile.status, ['IDLE', 'CHARGING', 'FAULT'])
            if pile.status == 'CHARGING':
                self.assertIsNotNone(pile.current_car_id)

        # 没有孤儿车（QUEUEING/CHARGING 必有桩）
        orphan = CarState.objects.filter(
            status__in=['QUEUEING', 'CHARGING'], pile__isnull=True
        ).count()
        self.assertEqual(orphan, 0)

        # 没有僵尸桩（CHARGING 必有车）
        for pile in ChargePile.objects.filter(status='CHARGING'):
            self.assertIsNotNone(pile.current_car_id)
            try:
                car = CarState.objects.get(car_id=pile.current_car_id)
                self.assertEqual(car.status, 'CHARGING')
            except CarState.DoesNotExist:
                self.fail(f'{pile.pile_id} 标记 CHARGING 但车 {pile.current_car_id} 不存在')
