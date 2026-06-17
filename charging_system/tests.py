from django.test import TestCase
from django.utils import timezone
from charging_system.models import ChargePile, CarState
from charging_system.services.pile_service import (
    powerOn, powerOff, setParameters, Start_ChargingPile, get_pile_parameters,
    Query_PileState, Query_QueueState,
    PEAK_PRICE, NORMAL_PRICE, VALLEY_PRICE, SERVICE_FEE_RATE, FAST_RATE, TRICKLE_RATE
)


class PileServiceTests(TestCase):
    """测试充电桩管理与监控模块 - 组员D负责功能"""

    def setUp(self):
        """初始化测试数据"""
        # 创建测试充电桩
        self.pile1 = ChargePile.objects.create(pile_id='P001', mode='F', status='IDLE')
        self.pile2 = ChargePile.objects.create(pile_id='P002', mode='T', status='FAULT')
        self.pile3 = ChargePile.objects.create(pile_id='P003', mode='F', status='IDLE')
        
        # 创建测试车辆
        self.car1 = CarState.objects.create(
            car_id='C001', mode='F', request_amount=50.0,
            status='WAITING', pile=None
        )
        
        # 重置全局参数到默认值
        setParameters(
            peak_price=1.0,
            normal_price=0.7,
            valley_price=0.4,
            service_fee_rate=0.8,
            fast_rate=30.0,
            trickle_rate=10.0
        )

    def test_powerOn_normal(self):
        """测试 powerOn - 正常开启故障充电桩"""
        self.assertEqual(self.pile2.status, 'FAULT')
        
        result = powerOn('P002')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '充电桩 P002 已成功开启')
        
        self.pile2.refresh_from_db()
        self.assertEqual(self.pile2.status, 'IDLE')
        self.assertIsNone(self.pile2.current_car_id)

    def test_powerOn_already_idle(self):
        """测试 powerOn - 充电桩已处于开启状态"""
        result = powerOn('P001')
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '充电桩 P001 已处于开启状态')

    def test_powerOn_not_exist(self):
        """测试 powerOn - 充电桩不存在"""
        result = powerOn('P999')
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '充电桩 P999 不存在')

    def test_powerOff_normal(self):
        """测试 powerOff - 正常关闭空闲充电桩"""
        self.assertEqual(self.pile1.status, 'IDLE')
        
        result = powerOff('P001')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '充电桩 P001 已成功关闭')
        
        self.pile1.refresh_from_db()
        self.assertEqual(self.pile1.status, 'FAULT')

    def test_powerOff_already_fault(self):
        """测试 powerOff - 充电桩已处于关闭状态"""
        result = powerOff('P002')
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '充电桩 P002 已处于关闭状态')

    def test_powerOff_with_charging_car(self):
        """测试 powerOff - 关闭正在充电的充电桩（触发重调度）"""
        self.pile1.status = 'CHARGING'
        self.pile1.current_car_id = 'C001'
        self.pile1.save()
        
        self.car1.status = 'CHARGING'
        self.car1.pile = self.pile1
        self.car1.save()
        
        # 将其他快充桩也设置为故障，确保重调度不会成功
        self.pile3.status = 'FAULT'
        self.pile3.save()
        
        result = powerOff('P001')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '充电桩 P001 已强制关闭')
        self.assertEqual(result['affected_car'], 'C001')
        
        self.pile1.refresh_from_db()
        self.assertEqual(self.pile1.status, 'FAULT')
        
        self.car1.refresh_from_db()
        # 没有其他可用充电桩，车辆应处于故障等待状态
        self.assertEqual(self.car1.status, 'FAULT_WAITING')
        self.assertIsNone(self.car1.pile)

    def test_setParameters_all(self):
        """测试 setParameters - 同时修改所有参数"""
        result = setParameters(
            peak_price=1.2,
            normal_price=0.8,
            valley_price=0.5,
            service_fee_rate=0.9,
            fast_rate=35.0,
            trickle_rate=12.0
        )
        
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '参数调整成功')
        
        params = get_pile_parameters()
        self.assertEqual(params['peak_price'], 1.2)
        self.assertEqual(params['normal_price'], 0.8)
        self.assertEqual(params['valley_price'], 0.5)
        self.assertEqual(params['service_fee_rate'], 0.9)
        self.assertEqual(params['fast_rate'], 35.0)
        self.assertEqual(params['trickle_rate'], 12.0)

    def test_setParameters_partial(self):
        """测试 setParameters - 只修改部分参数"""
        result = setParameters(peak_price=1.5, service_fee_rate=1.0)
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['changes']), 2)
        
        params = get_pile_parameters()
        self.assertEqual(params['peak_price'], 1.5)
        self.assertEqual(params['service_fee_rate'], 1.0)
        self.assertEqual(params['normal_price'], 0.7)
        self.assertEqual(params['valley_price'], 0.4)

    def test_setParameters_invalid(self):
        """测试 setParameters - 无效参数"""
        result = setParameters(peak_price=-1.0)
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '峰时电价必须大于0')
        
        result = setParameters(fast_rate=0)
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '快充速度必须大于0')

    def test_setParameters_no_change(self):
        """测试 setParameters - 未提供任何有效参数"""
        result = setParameters()
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '未提供任何有效参数修改')

    def test_Start_ChargingPile_normal(self):
        """测试 Start_ChargingPile - 正常激活充电桩（有排队车辆）"""
        car = CarState.objects.create(
            car_id='C002', mode='F', request_amount=30.0,
            status='QUEUEING', pile=self.pile1, queue_index=1
        )
        
        result = Start_ChargingPile('P001')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['action'], 'STARTED')
        self.assertEqual(result['car_id'], 'C002')
        
        self.pile1.refresh_from_db()
        self.assertEqual(self.pile1.status, 'CHARGING')
        self.assertEqual(self.pile1.current_car_id, 'C002')
        
        car.refresh_from_db()
        self.assertEqual(car.status, 'CHARGING')
        self.assertEqual(car.queue_index, 0)

    def test_Start_ChargingPile_no_queue(self):
        """测试 Start_ChargingPile - 专属队列无车（触发全局调度）"""
        result = Start_ChargingPile('P001')
        
        self.assertTrue(result['success'])
        self.assertIn('已触发全局调度', result['message'])

    def test_Start_ChargingPile_fault(self):
        """测试 Start_ChargingPile - 充电桩处于故障状态"""
        result = Start_ChargingPile('P002')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '充电桩 P002 处于故障状态，无法激活')

    def test_Start_ChargingPile_charging(self):
        """测试 Start_ChargingPile - 充电桩正在充电中"""
        self.pile1.status = 'CHARGING'
        self.pile1.current_car_id = 'C001'
        self.pile1.save()
        
        result = Start_ChargingPile('P001')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '充电桩 P001 正在充电中')

    def test_Start_ChargingPile_not_exist(self):
        """测试 Start_ChargingPile - 充电桩不存在"""
        result = Start_ChargingPile('P999')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '充电桩 P999 不存在')

    def test_get_pile_parameters(self):
        """测试 get_pile_parameters - 获取当前参数配置"""
        params = get_pile_parameters()
        
        self.assertEqual(params['peak_price'], 1.0)
        self.assertEqual(params['normal_price'], 0.7)
        self.assertEqual(params['valley_price'], 0.4)
        self.assertEqual(params['service_fee_rate'], 0.8)
        self.assertEqual(params['fast_rate'], 30.0)
        self.assertEqual(params['trickle_rate'], 10.0)
        self.assertEqual(params['peak_hours'], [(10, 15), (18, 21)])
        self.assertEqual(params['normal_hours'], [(7, 10), (15, 18), (21, 23)])


class PileServiceTestsMemberE(TestCase):
    """测试充电桩管理与监控模块 - 组员E负责功能"""

    def setUp(self):
        """初始化测试数据"""
        # 创建测试充电桩
        self.pile1 = ChargePile.objects.create(
            pile_id='P001', mode='F', status='CHARGING', current_car_id='C001',
            total_charge_amount=100.0, total_charge_times=5, total_charge_duration_minutes=120.0
        )
        self.pile2 = ChargePile.objects.create(
            pile_id='P002', mode='T', status='IDLE',
            total_charge_amount=50.0, total_charge_times=3, total_charge_duration_minutes=180.0
        )
        self.pile3 = ChargePile.objects.create(
            pile_id='P003', mode='F', status='FAULT',
            total_charge_amount=0.0, total_charge_times=0, total_charge_duration_minutes=0.0
        )
        
        # 创建测试车辆
        self.car1 = CarState.objects.create(
            car_id='C001', mode='F', request_amount=50.0, charged_amount=20.0,
            status='CHARGING', pile=self.pile1, queue_index=0, total_fee=25.0
        )
        self.car2 = CarState.objects.create(
            car_id='C002', mode='F', request_amount=40.0, charged_amount=10.0,
            status='QUEUEING', pile=self.pile1, queue_index=1, total_fee=15.0
        )
        self.car3 = CarState.objects.create(
            car_id='C003', mode='F', request_amount=30.0, charged_amount=5.0,
            status='QUEUEING', pile=self.pile1, queue_index=2, total_fee=10.0
        )

    def test_Query_PileState_single(self):
        """测试 Query_PileState - 查询单个充电桩状态"""
        result = Query_PileState('P001')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pile_id'], 'P001')
        self.assertEqual(result['mode'], 'F')
        self.assertEqual(result['mode_display'], '快充')
        self.assertEqual(result['status'], 'CHARGING')
        self.assertEqual(result['status_display'], '充电中')
        
        # 检查当前充电车辆信息
        self.assertIsNotNone(result['current_car'])
        self.assertEqual(result['current_car']['car_id'], 'C001')
        self.assertEqual(result['current_car']['charged_amount'], 20.0)
        
        # 检查5个运行指标
        metrics = result['metrics']
        self.assertEqual(metrics['total_charge_amount'], 100.0)
        self.assertEqual(metrics['total_charge_times'], 5)
        self.assertEqual(metrics['total_charge_duration_minutes'], 120.0)
        self.assertEqual(metrics['queue_length'], 2)
        self.assertEqual(metrics['average_charge_per_time'], 20.0)

    def test_Query_PileState_all(self):
        """测试 Query_PileState - 查询所有充电桩状态"""
        result = Query_PileState()
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['piles']), 3)
        
        # 验证充电桩列表
        pile_ids = [p['pile_id'] for p in result['piles']]
        self.assertIn('P001', pile_ids)
        self.assertIn('P002', pile_ids)
        self.assertIn('P003', pile_ids)

    def test_Query_PileState_not_exist(self):
        """测试 Query_PileState - 查询不存在的充电桩"""
        result = Query_PileState('P999')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '充电桩 P999 不存在')

    def test_Query_PileState_no_current_car(self):
        """测试 Query_PileState - 充电桩无当前充电车辆"""
        result = Query_PileState('P002')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pile_id'], 'P002')
        self.assertEqual(result['status'], 'IDLE')
        self.assertIsNone(result['current_car'])

    def test_Query_QueueState_normal(self):
        """测试 Query_QueueState - 查询充电桩专属队列"""
        result = Query_QueueState('P001')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pile_id'], 'P001')
        self.assertEqual(result['pile_mode'], 'F')
        self.assertEqual(result['pile_status'], 'CHARGING')
        self.assertEqual(result['queue_length'], 2)
        self.assertEqual(result['max_queue_limit'], 4)
        
        # 验证当前充电车辆
        self.assertIsNotNone(result['current_car'])
        self.assertEqual(result['current_car']['car_id'], 'C001')
        
        # 验证队列列表
        queue_cars = result['queue_list']
        self.assertEqual(len(queue_cars), 2)
        self.assertEqual(queue_cars[0]['car_id'], 'C002')
        self.assertEqual(queue_cars[0]['queue_index'], 1)
        self.assertEqual(queue_cars[1]['car_id'], 'C003')
        self.assertEqual(queue_cars[1]['queue_index'], 2)

    def test_Query_QueueState_no_queue(self):
        """测试 Query_QueueState - 充电桩无排队车辆"""
        result = Query_QueueState('P002')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['queue_length'], 0)
        self.assertEqual(len(result['queue_list']), 0)
        self.assertIsNone(result['current_car'])

    def test_Query_QueueState_not_exist(self):
        """测试 Query_QueueState - 查询不存在的充电桩"""
        result = Query_QueueState('P999')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '充电桩 P999 不存在')

    def test_Query_QueueState_fault_pile(self):
        """测试 Query_QueueState - 查询故障充电桩"""
        result = Query_QueueState('P003')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pile_status'], 'FAULT')
        self.assertEqual(result['queue_length'], 0)
