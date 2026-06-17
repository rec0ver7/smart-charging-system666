from django.db import models

class ChargePile(models.Model):
    """
    ⚡ 充电桩模型（对应大作业中的 2个快充 + 3个慢充桩）
    """
    STATUS_CHOICES = (
        ('IDLE', '空闲'),
        ('CHARGING', '充电中'),
        ('FAULT', '故障'),
    )
    TYPE_CHOICES = (
        ('F', '快充'),
        ('T', '慢充'),
    )
    
    pile_id = models.CharField(max_length=20, primary_key=True, verbose_name="充电桩ID")
    mode = models.CharField(max_length=2, choices=TYPE_CHOICES, verbose_name="充电桩类型(F/T)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IDLE', verbose_name="运行状态")
    current_car_id = models.CharField(max_length=20, null=True, blank=True, verbose_name="当前正在充电的车辆ID")
    
    # 统计指标（用于管理员大屏监控报表展示）
    total_charge_amount = models.FloatField(default=0.0, verbose_name="累计充电量(度)")
    total_charge_times = models.IntegerField(default=0, verbose_name="累计充电次数")
    total_charge_duration_minutes = models.FloatField(default=0.0, verbose_name="累计充电时长(分钟)")

    def __str__(self):
        return f"{self.pile_id} ({self.get_mode_display()}) - {self.get_status_display()}"


class CarState(models.Model):
    """
    🚗 车辆状态机模型（完美闭环车主在等候区、充电区的排队状态切换）
    """
    STATE_CHOICES = (
        ('WAITING', '等候区排队中'),            # 在总等候区排队，未分配具体的桩
        ('QUEUEING', '充电区专属队列排队中'),   # 已分配到具体桩的后方停车位（上限4辆）
        ('CHARGING', '正在充电'),               # 正在充电中
        ('FINISHED', '充电完成'),               # 正常充满或用户主动取消结束
        ('FAULT_WAITING', '故障再调度等待中'),   # 桩突发故障后，等待系统重新分配
    )
    MODE_CHOICES = (
        ('F', '快充'),
        ('T', '慢充'),
    )

    car_id = models.CharField(max_length=20, primary_key=True, verbose_name="车辆ID")
    mode = models.CharField(max_length=2, choices=MODE_CHOICES, default='T', verbose_name="充电模式")
    request_amount = models.FloatField(default=0.0, verbose_name="请求充电量(度)")
    charged_amount = models.FloatField(default=0.0, verbose_name="已充电量(度)")
    status = models.CharField(max_length=20, choices=STATE_CHOICES, default='WAITING', verbose_name="车辆状态")
    
    # 建立多对一外键：一辆车同一时间只能被分到一个充电桩专属队列
    pile = models.ForeignKey(ChargePile, on_delete=models.SET_NULL, null=True, blank=True, related_name="cars_in_queue", verbose_name="所属充电桩")
    queue_index = models.IntegerField(default=0, verbose_name="在专属队列中的排队顺位(1-4)")
    
    # 时间戳（用于时间片轮询和时序调度算法的绝对公平判定）
    request_time = models.DateTimeField(auto_now_add=True, verbose_name="发起充电请求时间")
    start_time = models.DateTimeField(null=True, blank=True, verbose_name="开始充电时间")
    last_update_time = models.DateTimeField(null=True, blank=True, verbose_name="上一次计算电量的结算点")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="结束充电/移出系统时间")
    
    total_fee = models.FloatField(default=0.0, verbose_name="当前已产生的累计总费用")

    def __str__(self):
        return f"车辆 {self.car_id} ({self.get_status_display()})"


class BillRecord(models.Model):
    """
    💰 详单与账单持久化模型（用于生成用户最终账单和管理员财务报表）
    """
    bill_id = models.AutoField(primary_key=True)
    car_id = models.CharField(max_length=20, verbose_name="车辆ID")
    pile_id = models.CharField(max_length=20, verbose_name="充电桩ID")
    charge_amount = models.FloatField(verbose_name="充电量(度)")
    start_time = models.DateTimeField(verbose_name="充电开始时间")
    end_time = models.DateTimeField(verbose_name="充电结束时间")
    charge_duration_minutes = models.FloatField(verbose_name="充电持续时间(分钟)")
    
    # 严格按照PPT要求：总费用 = 充电费 + 服务费
    charge_fee = models.FloatField(verbose_name="分时充电费(元)")
    service_fee = models.FloatField(verbose_name="固定服务费(元)")
    total_fee = models.FloatField(verbose_name="总费用(元)")

    def __str__(self):
        return f"账单 {self.bill_id} - 车 {self.car_id} - 总计: {self.total_fee}元"
