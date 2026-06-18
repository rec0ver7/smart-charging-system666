"""
初始化数据：创建 5 个充电桩（2 快充 + 3 慢充）
用法: python manage.py seed_data [--reset]
"""
from django.core.management.base import BaseCommand
from charging_system.models import ChargePile, CarState, BillRecord


class Command(BaseCommand):
    help = '初始化充电桩数据（5个桩：2快充 + 3慢充）'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='清除所有数据后重建')

    def handle(self, *args, **options):
        if options['reset']:
            BillRecord.objects.all().delete()
            CarState.objects.all().delete()
            ChargePile.objects.all().delete()
            self.stdout.write(self.style.WARNING('已清除所有数据'))

        created = []
        for pid, mode in [('PILE_F1', 'F'), ('PILE_F2', 'F'),
                          ('PILE_T1', 'T'), ('PILE_T2', 'T'), ('PILE_T3', 'T')]:
            pile, is_new = ChargePile.objects.get_or_create(
                pile_id=pid,
                defaults={'mode': mode, 'status': 'IDLE'}
            )
            if is_new:
                created.append(pid)

        if created:
            self.stdout.write(self.style.SUCCESS(
                f'已创建 {len(created)} 个充电桩: {", ".join(created)}'
            ))
        else:
            self.stdout.write('充电桩已存在，未重复创建（使用 --reset 可重置）')
