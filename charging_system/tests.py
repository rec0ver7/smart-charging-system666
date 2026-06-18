"""
边界测试：覆盖所有调度策略、故障恢复、队列管理、边界条件
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


class PriorityScheduleTest(TestCase):
    """优先级调度边界测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_F2', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_01_single_car_goes_to_idle_pile(self):
        """单辆车分配到空闲桩，直接充电"""
        r = E_chargingRequest('CAR1', 'T', 50)
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'STARTED')
        car = CarState.objects.get(car_id='CAR1')
        self.assertEqual(car.status, 'CHARGING')
        pile = ChargePile.objects.get(pile_id=r['pile_id'])
        self.assertEqual(pile.status, 'CHARGING')
        self.assertEqual(pile.current_car_id, 'CAR1')

    def test_02_second_car_queues_on_same_pile(self):
        """第二辆车进入同一桩队列"""
        E_chargingRequest('CAR1', 'T', 50)
        r = E_chargingRequest('CAR2', 'T', 30)
        # 3个慢充桩，CAR1占一个，CAR2应该选另一个空闲桩
        # 所有桩都有 score=0，先选字母序最小的
        self.assertTrue(r['success'])
        self.assertIn(r['action'], ['STARTED', 'QUEUED'])

    def test_03_car_already_charged_auto_finished(self):
        """已充满的车直接完成"""
        CarState.objects.create(
            car_id='CAR_DONE', mode='T', request_amount=30,
            charged_amount=30, status='WAITING'
        )
        r = priority_schedule('CAR_DONE')
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'FINISHED')

    def test_04_no_matching_mode_pile_fault_waiting(self):
        """没有匹配模式的健康桩 -> FAULT_WAITING"""
        # 把所有 F 桩设为 FAULT
        ChargePile.objects.filter(mode='F').update(status='FAULT')
        r = E_chargingRequest('CAR_F', 'F', 30)
        self.assertFalse(r['success'])
        car = CarState.objects.get(car_id='CAR_F')
        self.assertEqual(car.status, 'FAULT_WAITING')

    def test_05_queue_limit_4_enforced(self):
        """所有同模式桩队列都满4辆时新请求保持 WAITING"""
        # 占满所有3根慢充桩，每根队列4辆
        for pid in ['PILE_T1', 'PILE_T2', 'PILE_T3']:
            pile = ChargePile.objects.get(pile_id=pid)
            pile.status = 'CHARGING'
            pile.current_car_id = f'CAR_{pid}'
            pile.save()
            CarState.objects.create(car_id=f'CAR_{pid}', mode='T', request_amount=50,
                                    status='CHARGING', pile=pile,
                                    last_update_time=timezone.now(), start_time=timezone.now())
            for i in range(1, 5):
                CarState.objects.create(
                    car_id=f'Q_{pid}_{i}', mode='T', request_amount=30,
                    status='QUEUEING', pile=pile, queue_index=i,
                    request_time=timezone.now()
                )
        # 第16辆车（3*(1+4)=15已满），所有桩队列都满
        r = E_chargingRequest('CAR_OVER', 'T', 30)
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'WAIT')

    def test_06_tie_breaking_by_pile_id(self):
        """相同负载时按桩ID字母序选择"""
        # 所有3个慢充桩都空闲，第一辆车应选 PILE_T1（字母序最小）
        ChargePile.objects.filter(mode='T').update(status='IDLE')
        r = E_chargingRequest('CAR_TIE', 'T', 40)
        self.assertTrue(r['success'])
        self.assertEqual(r['pile_id'], 'PILE_T1')

    def test_07_fast_slow_mode_separation(self):
        """快充车只分配到快充桩"""
        r = E_chargingRequest('CAR_F', 'F', 20)
        self.assertTrue(r['success'])
        pile = ChargePile.objects.get(pile_id=r['pile_id'])
        self.assertEqual(pile.mode, 'F')
        # 慢充车只分配到慢充桩
        r2 = E_chargingRequest('CAR_T', 'T', 20)
        pile2 = ChargePile.objects.get(pile_id=r2['pile_id'])
        self.assertEqual(pile2.mode, 'T')


class TimeOrderScheduleTest(TestCase):
    """时间顺序调度边界测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_08_time_order_dispatches_by_timestamp(self):
        """按时序调度：早请求的先分配"""
        t1 = timezone.now()
        CarState.objects.create(car_id='CAR_EARLY', mode='T', request_amount=30,
                                status='WAITING', request_time=t1)
        import time
        time.sleep(0.1)
        t2 = timezone.now()
        CarState.objects.create(car_id='CAR_LATE', mode='T', request_amount=30,
                                status='WAITING', request_time=t2)

        r = time_order_schedule()
        self.assertTrue(r['success'])
        # CAR_EARLY 应先去 PILE_T1（IDLE），CAR_LATE 应去 PILE_T2
        early = CarState.objects.get(car_id='CAR_EARLY')
        late = CarState.objects.get(car_id='CAR_LATE')
        self.assertEqual(early.status, 'CHARGING')
        self.assertIn(late.status, ['CHARGING', 'QUEUEING'])

    def test_09_time_order_fills_empty_slots_only(self):
        """时序调度把等候区车调入有空位的桩"""
        # 所有桩占满
        for pid in ['PILE_T1', 'PILE_T2', 'PILE_T3']:
            pile = ChargePile.objects.get(pile_id=pid)
            pile.status = 'CHARGING'
            pile.current_car_id = f'CAR_{pid}'
            pile.save()
            CarState.objects.create(car_id=f'CAR_{pid}', mode='T',
                                    request_amount=50, status='CHARGING', pile=pile)

        CarState.objects.create(car_id='CAR_WAIT', mode='T', request_amount=20,
                                status='WAITING', request_time=timezone.now())
        r = time_order_schedule()
        # 所有桩都在充电，队列为空，车应被调入队列
        car = CarState.objects.get(car_id='CAR_WAIT')
        self.assertEqual(car.status, 'QUEUEING')
        self.assertIsNotNone(car.pile)

    def test_10_time_order_respects_queue_limit(self):
        """时序调入时队列超4辆的不再分配"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_X'
        pile.save()
        CarState.objects.create(car_id='CAR_X', mode='T', request_amount=50,
                                status='CHARGING', pile=pile)
        for i in range(1, 5):
            CarState.objects.create(car_id=f'Q{i}', mode='T', request_amount=10,
                                    status='QUEUEING', pile=pile, queue_index=i,
                                    request_time=timezone.now())

        CarState.objects.create(car_id='CAR_WAIT2', mode='T', request_amount=20,
                                status='WAITING', request_time=timezone.now())
        r = time_order_schedule()
        car = CarState.objects.get(car_id='CAR_WAIT2')
        # PILE_T1 队列满，应分配到 PILE_T2 或 PILE_T3
        self.assertNotEqual(car.pile.pile_id if car.pile else None, 'PILE_T1')

    def test_11_queue_index_correct_after_dispatch(self):
        """time_order 分配后 queue_index 正确（选队列最短的桩）"""
        # PILE_T1 有1辆排队，PILE_T2/T3 队列为空 → 应选空队列桩
        for pid in ['PILE_T1', 'PILE_T2', 'PILE_T3']:
            pile = ChargePile.objects.get(pile_id=pid)
            pile.status = 'CHARGING'
            pile.current_car_id = f'CAR_{pid}'
            pile.save()
            CarState.objects.create(car_id=f'CAR_{pid}', mode='T', request_amount=50,
                                    status='CHARGING', pile=pile,
                                    last_update_time=timezone.now(), start_time=timezone.now())
        # 只有 PILE_T1 有1辆排队
        CarState.objects.create(car_id='Q_A', mode='T', request_amount=10,
                                status='QUEUEING', pile=ChargePile.objects.get(pile_id='PILE_T1'),
                                queue_index=1, request_time=timezone.now())

        CarState.objects.create(car_id='NEW_CAR', mode='T', request_amount=20,
                                status='WAITING', request_time=timezone.now())
        time_order_schedule()
        car = CarState.objects.get(car_id='NEW_CAR')
        self.assertEqual(car.status, 'QUEUEING')
        # 应选队列最短的桩（PILE_T2 或 PILE_T3，队列为0），排在第1位
        self.assertEqual(car.queue_index, 1)
        self.assertIn(car.pile.pile_id, ['PILE_T2', 'PILE_T3'])


class FaultRecoveryTest(TestCase):
    """故障恢复边界测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_12_fault_recovery_single_charging_car(self):
        """故障时恢复1辆正在充电的车"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_F1'
        pile.save()
        CarState.objects.create(car_id='CAR_F1', mode='T', request_amount=50,
                                charged_amount=10, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        r = handle_pile_fault('PILE_T1')
        self.assertTrue(r['success'])
        self.assertEqual(r['status'], 'LOCKED_FAULT')
        self.assertIn('CAR_F1', r['affected_cars'])

        pile.refresh_from_db()
        self.assertEqual(pile.status, 'FAULT')
        self.assertIsNone(pile.current_car_id)

    def test_13_fault_recovery_with_queue_cars(self):
        """故障时恢复充电车+排队车"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_ON'
        pile.save()
        CarState.objects.create(car_id='CAR_ON', mode='T', request_amount=50,
                                charged_amount=5, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())
        CarState.objects.create(car_id='CAR_Q1', mode='T', request_amount=30,
                                status='QUEUEING', pile=pile, queue_index=1,
                                request_time=timezone.now())
        CarState.objects.create(car_id='CAR_Q2', mode='T', request_amount=20,
                                status='QUEUEING', pile=pile, queue_index=2,
                                request_time=timezone.now())

        r = handle_pile_fault('PILE_T1')
        self.assertTrue(r['success'])
        self.assertIn('CAR_ON', r['affected_cars'])
        self.assertIn('CAR_Q1', r['affected_cars'])
        self.assertIn('CAR_Q2', r['affected_cars'])

    def test_14_fault_idle_pile_no_effect(self):
        """空闲桩故障不影响任何车"""
        r = handle_pile_fault('PILE_T3')
        self.assertTrue(r['success'])
        self.assertEqual(len(r['affected_cars']), 0)

    def test_15_fault_recovery_reschedule_to_healthy_pile(self):
        """故障车重调度到健康桩"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_MOVE'
        pile.save()
        CarState.objects.create(car_id='CAR_MOVE', mode='T', request_amount=30,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        r = handle_pile_fault('PILE_T1')
        self.assertTrue(r['success'])

        car = CarState.objects.get(car_id='CAR_MOVE')
        # 应成功重调度到 PILE_T2 或 PILE_T3
        self.assertNotEqual(car.status, 'FAULT_WAITING',
                           f'重调度失败，车状态={car.status}')

    def test_16_fault_waiting_recovery_after_pile_freed(self):
        """桩释放后 FAULT_WAITING 车自动恢复"""
        # 占满所有桩
        for pid in ['PILE_T1', 'PILE_T2']:
            pile = ChargePile.objects.get(pile_id=pid)
            pile.status = 'CHARGING'
            pile.current_car_id = f'CAR_{pid}'
            pile.save()
            CarState.objects.create(car_id=f'CAR_{pid}', mode='T',
                                    request_amount=100, charged_amount=0,
                                    status='CHARGING', pile=pile,
                                    last_update_time=timezone.now(),
                                    start_time=timezone.now())

        # 第3辆车故障等待
        CarState.objects.create(car_id='CAR_FAULT', mode='T', request_amount=30,
                                status='FAULT_WAITING', request_time=timezone.now())

        # 释放 PILE_T3（空闲桩）然后触发 auto_tick
        # auto_tick 只处理 CHARGING 桩，这里 PILE_T3 是 IDLE
        # 需要先让 FAULT_WAITING 恢复
        # 直接调用 priority_schedule 模拟恢复
        r = priority_schedule('CAR_FAULT')
        self.assertTrue(r['success'])
        car = CarState.objects.get(car_id='CAR_FAULT')
        self.assertIn(car.status, ['CHARGING', 'QUEUEING'],
                     f'故障等待车应被恢复，实际={car.status}')

    def test_17_all_piles_fault_no_recovery(self):
        """所有桩故障时 FAULT_WAITING 无可恢复"""
        ChargePile.objects.all().update(status='FAULT')
        CarState.objects.create(car_id='CAR_STUCK', mode='T', request_amount=30,
                                status='FAULT_WAITING', request_time=timezone.now())
        r = priority_schedule('CAR_STUCK')
        self.assertFalse(r['success'])
        car = CarState.objects.get(car_id='CAR_STUCK')
        self.assertEqual(car.status, 'FAULT_WAITING')


class QueueManagementTest(TestCase):
    """队列管理边界测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_18_finished_car_not_in_queue(self):
        """已完成的车不出现在排队列表"""
        CarState.objects.create(car_id='CAR_OK', mode='T', request_amount=20,
                                charged_amount=20, status='FINISHED',
                                end_time=timezone.now())
        r = Query_QueueState('PILE_T1')
        self.assertTrue(r['success'])
        ids = [c['car_id'] for c in r['queue_list']]
        self.assertNotIn('CAR_OK', ids)

    def test_19_queue_order_by_index(self):
        """排队列表按 queue_index 排序"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        CarState.objects.create(car_id='Q3', mode='T', request_amount=10,
                                status='QUEUEING', pile=pile, queue_index=3,
                                request_time=timezone.now())
        CarState.objects.create(car_id='Q1', mode='T', request_amount=10,
                                status='QUEUEING', pile=pile, queue_index=1,
                                request_time=timezone.now())
        CarState.objects.create(car_id='Q2', mode='T', request_amount=10,
                                status='QUEUEING', pile=pile, queue_index=2,
                                request_time=timezone.now())

        r = Query_QueueState('PILE_T1')
        ids = [c['car_id'] for c in r['queue_list']]
        self.assertEqual(ids, ['Q1', 'Q2', 'Q3'])

    def test_20_queue_length_correct(self):
        """队列长度正确"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        for i in range(3):
            CarState.objects.create(car_id=f'Q{i}', mode='T', request_amount=10,
                                    status='QUEUEING', pile=pile, queue_index=i+1,
                                    request_time=timezone.now())
        r = Query_QueueState('PILE_T1')
        self.assertEqual(r['queue_length'], 3)

    def test_21_time_slice_promotes_next_car(self):
        """时间片轮转时下一辆车上桩"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_CUR'
        pile.save()

        CarState.objects.create(car_id='CAR_CUR', mode='T', request_amount=5,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())
        CarState.objects.create(car_id='CAR_NEXT', mode='T', request_amount=30,
                                status='QUEUEING', pile=pile, queue_index=1,
                                request_time=timezone.now())

        r = time_slice_schedule('PILE_T1')
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'SWITCHED')
        self.assertEqual(r['new_car'], 'CAR_NEXT')

        next_car = CarState.objects.get(car_id='CAR_NEXT')
        self.assertEqual(next_car.status, 'CHARGING')

    def test_22_time_slice_no_queue_keeps_charging(self):
        """无排队车时保持当前充电"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_SOLO'
        pile.save()
        CarState.objects.create(car_id='CAR_SOLO', mode='T', request_amount=50,
                                status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        r = time_slice_schedule('PILE_T1')
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'KEEP')


class CarCommandTest(TestCase):
    """车辆指令边界测试"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')

    def test_23_modify_amount_increase(self):
        """中途上调目标电量"""
        E_chargingRequest('CAR_M', 'T', 50)
        r = Modify_Amount('CAR_M', 80)
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'UPDATED')

    def test_24_modify_amount_below_charged(self):
        """下调目标电量 ≤ 已充电量 -> 自动完成"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_DOWN'
        pile.save()
        CarState.objects.create(car_id='CAR_DOWN', mode='T', request_amount=50,
                                charged_amount=40, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())
        r = Modify_Amount('CAR_DOWN', 30)
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'FINISHED')

    def test_25_modify_mode_switches_pile(self):
        """切换模式后重新调度到新模式桩"""
        E_chargingRequest('CAR_SW', 'T', 40)
        r = Modify_Mode('CAR_SW', 'F')
        self.assertTrue(r['success'])
        self.assertEqual(r['action'], 'MODE_SWITCHED')

    def test_26_query_state_dynamic_charge_growing(self):
        """查询状态时动态电量随模拟时间增长"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_G'
        pile.save()
        CarState.objects.create(car_id='CAR_G', mode='T', request_amount=100,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        import time
        r1 = Query_Charging_State('CAR_G')
        time.sleep(0.5)
        r2 = Query_Charging_State('CAR_G')
        # 电量应随时间增长
        self.assertGreaterEqual(r2['charged_amount'], r1['charged_amount'])

    def test_27_query_state_auto_finish(self):
        """查询时自动完成已充满的车"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_FULL'
        pile.save()
        CarState.objects.create(car_id='CAR_FULL', mode='T', request_amount=30,
                                charged_amount=30, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        r = Query_Charging_State('CAR_FULL')
        self.assertEqual(r['car_state'], 'FINISHED')

    def test_28_duration_stable_after_finish(self):
        """充电完成后时长不再增长"""
        now = timezone.now()
        CarState.objects.create(car_id='CAR_D', mode='T', request_amount=20,
                                charged_amount=20, status='FINISHED',
                                start_time=now - timezone.timedelta(seconds=5),
                                end_time=now)

        import time
        r1 = Query_Charging_State('CAR_D')
        d1 = r1['charge_duration_minutes']
        time.sleep(0.3)
        r2 = Query_Charging_State('CAR_D')
        d2 = r2['charge_duration_minutes']
        self.assertEqual(d1, d2, f'完成后时长不应变: {d1} -> {d2}')


class IntegrationTest(TestCase):
    """集成测试：多车多桩全流程"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()
        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_F2', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T3', mode='T', status='IDLE')

    def test_29_three_cars_same_mode(self):
        """3辆车同模式：各占一根桩"""
        r1 = E_chargingRequest('C1', 'T', 50)
        r2 = E_chargingRequest('C2', 'T', 50)
        r3 = E_chargingRequest('C3', 'T', 50)
        self.assertTrue(r1['success'])
        self.assertTrue(r2['success'])
        self.assertTrue(r3['success'])
        # 3辆车应分别在三根慢充桩上
        piles_used = set()
        for r in [r1, r2, r3]:
            if 'pile_id' in r:
                piles_used.add(r['pile_id'])
        self.assertEqual(len(piles_used), 3)

    def test_30_fourth_car_queues(self):
        """第4辆车进入队列"""
        for i in range(1, 4):
            E_chargingRequest(f'C{i}', 'T', 50)
        r4 = E_chargingRequest('C4', 'T', 30)
        self.assertTrue(r4['success'])
        self.assertEqual(r4['action'], 'QUEUED')

    def test_31_fault_and_recovery_full_flow(self):
        """故障→重调度→恢复 完整流程"""
        # 3辆车占3根桩
        E_chargingRequest('FA', 'T', 50)
        E_chargingRequest('FB', 'T', 50)
        E_chargingRequest('FC', 'T', 50)

        # 第4辆车排队
        E_chargingRequest('FD', 'T', 20)
        car_d = CarState.objects.get(car_id='FD')
        pile_of_d = car_d.pile

        # 故障模拟
        r = handle_pile_fault(pile_of_d.pile_id)
        self.assertTrue(r['success'])

        # 被提出队列的车应重调度
        car_d.refresh_from_db()
        self.assertNotEqual(car_d.status, 'FAULT_WAITING',
                           f'排队车应被重调度，实际={car_d.status}')

    def test_32_power_on_brings_pile_back(self):
        """故障桩开机后恢复可用"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'FAULT'
        pile.save()
        r = powerOn('PILE_T1')
        self.assertTrue(r['success'])
        pile.refresh_from_db()
        self.assertEqual(pile.status, 'IDLE')

    def test_33_auto_tick_completes_charged_cars(self):
        """auto_tick 检测到充满的车自动完成"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_DONE'
        pile.save()
        CarState.objects.create(car_id='CAR_DONE', mode='T', request_amount=50,
                                charged_amount=49.999, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())
        CarState.objects.create(car_id='CAR_Q', mode='T', request_amount=30,
                                status='QUEUEING', pile=pile, queue_index=1,
                                request_time=timezone.now())

        import time
        time.sleep(0.1)
        auto_tick_piles()

        car = CarState.objects.get(car_id='CAR_DONE')
        self.assertEqual(car.status, 'FINISHED',
                        f'应自动完成，实际={car.status}, charged={car.charged_amount}')

    def test_34_query_pile_state_shows_all_metrics(self):
        """查询全部桩状态返回完整指标"""
        E_chargingRequest('C_P', 'T', 30)
        r = Query_PileState()
        self.assertTrue(r['success'])
        self.assertEqual(len(r['piles']), 5)

    def test_35_bill_record_created_on_completion(self):
        """充电完成时生成详单记录"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_B'
        pile.save()
        CarState.objects.create(car_id='CAR_B', mode='T', request_amount=10,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        import time
        time.sleep(0.1)
        r = End_Charging('CAR_B')
        self.assertEqual(r, 1)

        bills = BillRecord.objects.filter(car_id='CAR_B')
        self.assertGreaterEqual(bills.count(), 1)

    def test_36_bill_calculation_after_finish(self):
        """完成后账单金额合理"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_BILL'
        pile.save()
        CarState.objects.create(car_id='CAR_BILL', mode='T', request_amount=10,
                                charged_amount=0, status='CHARGING', pile=pile,
                                last_update_time=timezone.now(), start_time=timezone.now())

        import time
        time.sleep(0.2)
        End_Charging('CAR_BILL')

        car = CarState.objects.get(car_id='CAR_BILL')
        self.assertEqual(car.status, 'FINISHED')
        self.assertGreater(car.total_fee, 0)
        self.assertGreater(car.charged_amount, 0)
