"""
全面测试：验证充电完成自动结算、队列清理、时间不再增长
"""
from django.test import TestCase
from django.utils import timezone
from charging_system.models import ChargePile, CarState, BillRecord
from charging_system.services.dispatch_service import (
    E_chargingRequest, priority_schedule, time_slice_schedule, handle_pile_fault
)
from charging_system.services.car_service import (
    Start_Charging, End_Charging, Query_Charging_State
)
from charging_system.services.pile_service import Query_QueueState, Query_PileState


class ChargingCompletionTest(TestCase):
    """测试：充电达目标电量后自动完成，不再滞留队列"""

    def setUp(self):
        # 清理旧数据
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()

        # 创建测试用充电桩
        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T2', mode='T', status='IDLE')

    def test_01_priority_schedule_auto_finishes_fully_charged_car(self):
        """已充满的车通过 priority_schedule 时自动 FINISHED"""
        car = CarState.objects.create(
            car_id='CAR_DONE',
            mode='T',
            request_amount=50,
            charged_amount=50,
            status='WAITING',
        )
        result = priority_schedule('CAR_DONE')
        self.assertTrue(result['success'])
        self.assertEqual(result['action'], 'FINISHED')
        car.refresh_from_db()
        self.assertEqual(car.status, 'FINISHED')
        self.assertIsNone(car.pile)
        self.assertIsNotNone(car.end_time)

    def test_02_time_slice_finishes_car_when_target_reached(self):
        """time_slice_schedule 中车辆达目标电量后自动 FINISHED，不再回队列"""
        car = CarState.objects.create(
            car_id='CAR_ALMOST',
            mode='T',
            request_amount=50,
            charged_amount=49.999,
            status='CHARGING',
            pile=ChargePile.objects.get(pile_id='PILE_T1'),
            last_update_time=timezone.now(),
            start_time=timezone.now(),
        )
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_ALMOST'
        pile.save()

        # 创建一辆排队车来触发 time_slice
        CarState.objects.create(
            car_id='CAR_NEXT',
            mode='T',
            request_amount=30,
            charged_amount=0,
            status='QUEUEING',
            pile=pile,
            queue_index=1,
            request_time=timezone.now(),
        )

        import time
        time.sleep(0.1)  # 确保时间差不为0

        result = time_slice_schedule('PILE_T1')
        self.assertTrue(result['success'])

        car.refresh_from_db()
        self.assertEqual(car.status, 'FINISHED',
                         f'期望 FINISHED，实际 {car.status}，charged={car.charged_amount}')
        self.assertIsNone(car.pile)
        self.assertIsNotNone(car.end_time)

    def test_03_finished_car_not_in_queue(self):
        """充电完成的车不在排队列表中出现"""
        CarState.objects.create(
            car_id='CAR_OK',
            mode='T',
            request_amount=20,
            charged_amount=20,
            status='FINISHED',
            pile=None,
            end_time=timezone.now(),
        )
        result = Query_QueueState('PILE_T1')
        self.assertTrue(result['success'])
        car_ids = [c['car_id'] for c in result['queue_list']]
        self.assertNotIn('CAR_OK', car_ids)

    def test_04_duration_stable_after_finish(self):
        """充电完成后 duration 不再增长（两次查询应一致）"""
        now = timezone.now()
        CarState.objects.create(
            car_id='CAR_STABLE',
            mode='T',
            request_amount=30,
            charged_amount=30,
            status='FINISHED',
            start_time=now - timezone.timedelta(seconds=5),
            end_time=now,
        )
        res1 = Query_Charging_State('CAR_STABLE')
        d1 = res1['charge_duration_minutes']

        import time
        time.sleep(0.3)

        res2 = Query_Charging_State('CAR_STABLE')
        d2 = res2['charge_duration_minutes']

        self.assertEqual(d1, d2,
                         f'充电完成后时间不应变化: {d1} -> {d2}')

    def test_05_query_state_auto_completes_stuck_car(self):
        """Query_Charging_State 自动兜底完成已充满但未 FINISHED 的车"""
        car = CarState.objects.create(
            car_id='CAR_STUCK',
            mode='T',
            request_amount=25,
            charged_amount=25,
            status='CHARGING',
            pile=ChargePile.objects.get(pile_id='PILE_T1'),
            last_update_time=timezone.now(),
            start_time=timezone.now(),
        )
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_STUCK'
        pile.save()

        result = Query_Charging_State('CAR_STUCK')
        self.assertTrue(result['success'])
        self.assertEqual(result['car_state'], 'FINISHED')

        car.refresh_from_db()
        self.assertEqual(car.status, 'FINISHED')
        self.assertIsNone(car.pile)
        self.assertIsNotNone(car.end_time)

    def test_06_full_flow_request_to_finish(self):
        """完整流程：发起请求 -> 充电 -> 达到目标 -> 自动完成"""
        # 1. 发起充电请求
        res = E_chargingRequest('CAR_FLOW', 'T', 50.0)
        self.assertTrue(res['success'])
        self.assertIn(res['action'], ['STARTED', 'QUEUED'])

        # 2. 模拟充电到几乎满
        car = CarState.objects.get(car_id='CAR_FLOW')
        car.charged_amount = 50.0
        car.save()

        # 3. 通过 Query_Charging_State 兜底完成
        res = Query_Charging_State('CAR_FLOW')
        self.assertEqual(res['car_state'], 'FINISHED')

        car.refresh_from_db()
        self.assertEqual(car.status, 'FINISHED')
        self.assertIsNotNone(car.end_time)

    def test_07_queue_shows_only_queuing_cars(self):
        """排队列表只显示 QUEUEING 状态的车，不含已完成的"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        CarState.objects.create(
            car_id='CAR_Q1', mode='T', request_amount=30, charged_amount=0,
            status='QUEUEING', pile=pile, queue_index=1,
            request_time=timezone.now(),
        )
        CarState.objects.create(
            car_id='CAR_Q2', mode='T', request_amount=20, charged_amount=20,
            status='FINISHED', pile=None,
            end_time=timezone.now(),
        )

        result = Query_QueueState('PILE_T1')
        car_ids = [c['car_id'] for c in result['queue_list']]
        self.assertIn('CAR_Q1', car_ids)
        self.assertNotIn('CAR_Q2', car_ids)

    def test_08_handle_pile_fault_finishes_charged_car(self):
        """故障重调度时已充满的车直接完成"""
        pile = ChargePile.objects.get(pile_id='PILE_T1')
        pile.status = 'CHARGING'
        pile.current_car_id = 'CAR_FULL'
        pile.save()

        CarState.objects.create(
            car_id='CAR_FULL',
            mode='T',
            request_amount=40,
            charged_amount=39.999,
            status='CHARGING',
            pile=pile,
            last_update_time=timezone.now(),
            start_time=timezone.now(),
        )

        import time
        time.sleep(0.1)

        result = handle_pile_fault('PILE_T1')
        self.assertTrue(result['success'])

        car = CarState.objects.get(car_id='CAR_FULL')
        self.assertEqual(car.status, 'FINISHED',
                         f'故障时已充车应 FINISHED，实际 {car.status}')


class SystemIntegrationTest(TestCase):
    """系统集成测试：多车并发 + 队列轮转"""

    def setUp(self):
        CarState.objects.all().delete()
        ChargePile.objects.all().delete()
        BillRecord.objects.all().delete()

        ChargePile.objects.create(pile_id='PILE_F1', mode='F', status='IDLE')
        ChargePile.objects.create(pile_id='PILE_T1', mode='T', status='IDLE')

    def test_multi_car_queue_rotation(self):
        """多车排队轮转，充满后自动移出"""
        # 3辆车请求同一慢充桩
        for i in range(1, 4):
            res = E_chargingRequest(f'CAR_{i}', 'T', 10.0)
            self.assertTrue(res['success'], f'CAR_{i} 请求失败: {res}')

        pile = ChargePile.objects.get(pile_id='PILE_T1')

        # 手动置第一辆车为几乎充满
        car1 = CarState.objects.get(car_id='CAR_1')
        car1.charged_amount = 9.999
        car1.status = 'CHARGING'
        car1.save()

        # 触发 time_slice -> CAR_1 应 FINISHED -> CAR_2 上桩
        import time
        time.sleep(0.1)
        res = time_slice_schedule('PILE_T1')
        self.assertTrue(res['success'])

        car1.refresh_from_db()
        self.assertEqual(car1.status, 'FINISHED',
                         f'CAR_1 应已充满完成，实际 {car1.status}')
        self.assertIsNone(car1.pile)

        # CAR_2 和 CAR_3 应在队列中
        queue = Query_QueueState('PILE_T1')
        queue_ids = [c['car_id'] for c in queue['queue_list']]
        self.assertNotIn('CAR_1', queue_ids,
                         '已完成的 CAR_1 不应在排队列表中')
