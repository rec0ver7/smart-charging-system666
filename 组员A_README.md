# 组员 A —— 代码交付说明

## 负责模块

### 1. 车辆指令与状态维护模块 (`charging_system/services/car_service.py`)

| 函数 | 功能 | 状态 |
|------|------|------|
| `Modify_Amount(car_id, new_amount)` | 支持车主中途修改目标充电量。若新目标 <= 已充度数，自动结算并结束充电 | ✅ 已完成 |
| `Modify_Mode(car_id, new_mode)` | 支持车主中途切换快充(F)/慢充(T)模式。正在充电的车会先结算当前片段、释放旧桩，再重新调度到新模式充电桩 | ✅ 已完成 |

### 2. Views 接口封装 (`charging_system/views.py`)

| 接口路径 | 参数 | 功能 |
|----------|------|------|
| `GET /api/charging_request` | `car_id`, `mode`, `request_amount` | 提交充电请求 |
| `GET /api/query_state` | `car_id` | 实时查询充电状态(已充度数、费用等) |
| `GET /api/modify_amount` | `car_id`, `new_amount` | 修改目标充电量 |
| `GET /api/modify_mode` | `car_id`, `new_mode` | 切换快慢充模式 |
| `GET /api/cancel_charging` | `car_id` | 取消/结束充电并出具账单 |
| `GET /api/get_bill` | `car_id` | 获取最终合并总账单 |
| `GET /api/get_detailed_list` | `car_id` | 获取每段充电详单明细 |
| `GET /` | - | 车主端操作页面 (client.html) |

### 3. 车主端前端页面 (`charging_system/templates/client.html`)

- 表单操作区：车牌号输入、快/慢充模式选择、目标电量输入
- 功能按钮：提交充电请求、修改目标电量、切换快慢充、取消充电、查看账单、查看详单
- 实时状态面板：每2秒自动轮询后端，动态刷新已充电量、当前费用、剩余电量等
- 充电完成时自动弹窗展示最终费用详单

### 4. URL 路由配置 (`backend/urls.py`)

- 所有车主端 API 路径已在 `backend/urls.py` 中注册
- 根路径 `/` 指向车主端操作页面

### 5. Bug 修复

- `dispatch_service.py`: 修复了缺失的 `TIME_SCALE` 导入
- `dispatch_service.py`: 修复了 `E_chargingRequest()` 中不存在的 `total_capacity` 字段
- `car_service.py`: 修复 `Query_Charging_State()` 完成判断使用 DB 旧值而非动态计算值，导致单车上桩后永远无法自动完成
- `car_service.py`: 提取 `calc_display_charge()` 公用函数，统一客户端和管理端的实时动态电量计算
- `pile_service.py`: `Query_PileState()` / `Query_QueueState()` 改用动态计算电量，解决管理大屏显示滞后

## 如何运行

```bash
cd smart-charging-system666

# 安装依赖
pip install django django-cors-headers

# 数据库迁移
python manage.py migrate

# 启动服务器
python manage.py runserver
```

浏览器访问 `http://127.0.0.1:8000/` 即可使用车主端操作页面。

## API 调用示例

```javascript
// 提交充电请求
axios.get('/api/charging_request', {
    params: { car_id: '京A12345', mode: 'T', request_amount: 50 }
})

// 实时查询状态（建议每2秒轮询）
axios.get('/api/query_state', { params: { car_id: '京A12345' } })

// 修改目标电量
axios.get('/api/modify_amount', { params: { car_id: '京A12345', new_amount: 80 } })

// 切换快慢充
axios.get('/api/modify_mode', { params: { car_id: '京A12345', new_mode: 'F' } })

// 取消充电
axios.get('/api/cancel_charging', { params: { car_id: '京A12345' } })

// 查看账单
axios.get('/api/get_bill', { params: { car_id: '京A12345' } })
```

## 设计要点

- **数据库锁安全**：`Modify_Amount` 和 `Modify_Mode` 均使用 `transaction.atomic()` + `select_for_update()` 保证并发安全
- **阶段结算**：模式切换或电量修改触发充电结束时，会自动结算当前时间片段的电费并写入 `BillRecord` 表
- **无缝重调度**：模式切换后自动调用 `priority_schedule()` 将车辆重新分配到新模式的最优充电桩
