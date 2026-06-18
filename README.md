# ⚡ 智能充电桩调度计费系统

## 一、系统架构选择及说明（10%）

**架构选型：Django MTV（Model-Template-View）全栈单体架构**

| 层次 | 技术选型 | 说明 |
|------|---------|------|
| 数据层 (Model) | Django ORM + SQLite | 3 个核心实体类：`ChargePile`（充电桩）、`CarState`（车辆状态机）、`BillRecord`（详单账单）。使用 `select_for_update()` 行级锁保证并发安全 |
| 业务层 (Service) | 纯 Python 服务模块 | `dispatch_service.py`（调度算法）、`car_service.py`（车辆指令）、`bill_service.py`（分时计费引擎）、`pile_service.py`（充电桩管理）。全部使用 `transaction.atomic()` 事务包裹 |
| 接口层 (View) | Django View + JsonResponse | RESTful API，12 个核心接口，`csrf_exempt` 免除 CSRF 校验便于联调 |
| 展示层 (Template) | 原生 HTML + Axios 轮询 | `client.html`（车主端，2秒轮询）、`admin_dashboard.html`（管理大屏，1秒轮询） |

**选型理由**：
- Django ORM 的 `select_for_update` + `transaction.atomic` 天然支持并发充电请求的串行化调度，避免少充/过充
- MTV 分层清晰，Service 层纯逻辑无框架依赖，便于单元测试
- 前端极简（两个纯 HTML 页面），无需前后端分离框架，符合大作业验收场景

---

## 二、开发分工与完成情况

### 1. 数据模型与计费模块 — 组员 C
| 文件 | 内容 | 状态 |
|------|------|------|
| `charging_system/models.py` | ChargePile、CarState、BillRecord 三个核心实体类 | ✅ 已完成 |
| `charging_system/admin.py` | Django Admin 后台注册 | ✅ 已完成 |
| `charging_system/services/bill_service.py` | `calculate_phase_fee()` 峰平谷分时计费规则引擎 + TIME_SCALE 时间缩放系数；`Request_Bill()` 总账单；`Request_DetailedList()` 详单明细 | ✅ 已完成 |
| `charging_system/templates/client.html` | 车主端极简操作页面（前端主导） | ✅ 已完成 |

### 2. 中央调度算法模块 — 组长、组员 B、组员 D
| 负责人员 | 文件 | 内容 | 状态 |
|---------|------|------|------|
| 组长 | `dispatch_service.py` | `E_chargingRequest()` 核心叫号分配入口；`priority_schedule()` 优先级贪心调度算法；`time_slice_schedule()` 多车同桩时间片轮询算法 | ✅ 已完成 |
| 组员 D | `dispatch_service.py` | `time_order_schedule()` 严格按时间戳公平排队调度算法 | ✅ 已完成 |
| 组员 B | `dispatch_service.py` | `handle_pile_fault()` 桩突发故障时的车辆提取与无缝重调度恢复 | ✅ 已完成 |

### 3. 车辆指令与状态维护模块 — 组员 A、组员 B
| 负责人员 | 文件 | 内容 | 状态 |
|---------|------|------|------|
| 组员 A | `car_service.py` | `Modify_Amount()` 中途修改目标充电量；`Modify_Mode()` 中途切换快慢充模式 | ✅ 已完成 |
| 组员 B | `car_service.py` | `Start_Charging()` 控制车辆上桩；`End_Charging()` 充满/主动取消停止逻辑与计费结算；`Query_Charging_State()` 实时查询已充度数与费用 | ✅ 已完成 |
| 组员 A | `views.py` + `backend/urls.py` | 全部 12 个 API 接口的 View 封装与 URL 路由注册 | ✅ 已完成 |
| 组员 A | `templates/client.html` | 车主端前端页面（表单操作区 + 实时状态面板 + 账单弹窗） | ✅ 已完成 |

### 4. 充电桩管理与监控模块 — 组员 D、组员 E
| 负责人员 | 文件 | 内容 | 状态 |
|---------|------|------|------|
| 组员 D | `pile_service.py` | `powerOn()` / `powerOff()` 硬启停控制；`setParameters()` 在线调整电价参数；`Start_ChargingPile()` 激活状态机 | ✅ 已完成 |
| 组员 E | `pile_service.py` | `Query_PileState()` 收集 5 个充电桩运行指标；`Query_QueueState()` 获取专属队列车辆列表 | ✅ 已完成 |
| 组员 E | `templates/admin_dashboard.html` | 管理大屏前端页面（充电桩资产看板 + 实时排队详情 + 故障模拟按钮） | ✅ 已完成 |

### 5. Bug 修复 — 组员 A
- `dispatch_service.py`: 修复 `time_slice_schedule()` 中车辆达目标电量后仍被重新入队而非 FINISHED 的 bug
- `dispatch_service.py`: 修复 `priority_schedule()` 和 `handle_pile_fault()` 中已充满车辆未自动结算的问题
- `car_service.py`: 在 `Query_Charging_State()` 中增加已充满车辆的兜底自动完成逻辑
- `tests.py`: 编写 9 个测试用例覆盖充电完成自动结算、队列清理、时间不再增长等核心场景

---

## 三、系统事件人员分配表

> 作业要求第 4 条：作业的最后必须说明系统事件的人员分配

| 系统事件（用例） | 对应接口/函数 | 主要负责人 | 协同人员 |
|-----------------|-------------|-----------|---------|
| 用户发起充电请求 | `E_chargingRequest()` → `priority_schedule()` | 组长 | — |
| 优先级调度入队 | `priority_schedule()` | 组长 | — |
| 时间片轮询切换 | `time_slice_schedule()` | 组长 | — |
| 时间顺序公平调度 | `time_order_schedule()` | 组员 D | — |
| 充电桩故障重调度 | `handle_pile_fault()` | 组员 B | 组长 |
| 车辆上桩启动充电 | `Start_Charging()` | 组员 B | — |
| 充电结束/取消结算 | `End_Charging()` | 组员 B | — |
| 实时查询充电状态 | `Query_Charging_State()` | 组员 B | 组员 A |
| 修改目标充电量 | `Modify_Amount()` | 组员 A | — |
| 切换快慢充模式 | `Modify_Mode()` | 组员 A | — |
| 分时计费与账单生成 | `calculate_phase_fee()` / `Request_Bill()` | 组员 C | — |
| 充电桩硬启停控制 | `powerOn()` / `powerOff()` | 组员 D | — |
| 在线调整电价参数 | `setParameters()` | 组员 D | — |
| 激活桩状态机 | `Start_ChargingPile()` | 组员 D | — |
| 查询充电桩运行指标 | `Query_PileState()` | 组员 E | — |
| 查询专属队列车辆 | `Query_QueueState()` | 组员 E | — |
| 车主端 API 接口封装 | `views.py` 中 7 个车主端接口 | 组员 A | — |
| 管理大屏 API 接口封装 | `views.py` 中 5 个管理端接口 | 组员 A | — |
| 车主端前端页面 | `templates/client.html` | 组员 C | 组员 A |
| 管理大屏前端页面 | `templates/admin_dashboard.html` | 组员 E | 组员 D |
| 数据模型定义 | `models.py` | 组员 C | — |
| URL 路由配置 | `backend/urls.py` | 组员 A | — |

---

## 四、运行指南

```bash
cd smart-charging-system666
pip install django django-cors-headers
python manage.py migrate
python manage.py runserver
```

- 车主端：`http://127.0.0.1:8000/`
- 管理大屏：`http://127.0.0.1:8000/dashboard/`
- Django Admin：`http://127.0.0.1:8000/admin/`

## 五、API 接口一览

| 方法 | 路径 | 参数 | 说明 |
|------|------|------|------|
| GET | `/api/charging_request` | `car_id`, `mode`, `request_amount` | 提交充电请求 |
| GET | `/api/query_state` | `car_id` | 实时查询充电状态 |
| GET | `/api/modify_amount` | `car_id`, `new_amount` | 修改目标充电量 |
| GET | `/api/modify_mode` | `car_id`, `new_mode` | 切换快慢充模式 |
| GET | `/api/cancel_charging` | `car_id` | 取消/结束充电 |
| GET | `/api/get_bill` | `car_id` | 获取最终账单 |
| GET | `/api/get_detailed_list` | `car_id` | 获取充电详单 |
| GET | `/api/query_pile_state` | `pile_id`(可选) | 查询充电桩状态 |
| GET | `/api/query_queue_state` | `pile_id` | 查询排队队列 |
| GET | `/api/simulate_fault` | `pile_id` | 模拟充电桩故障 |
| GET | `/api/pile_power_on` | `pile_id` | 开启充电桩 |
| GET | `/api/pile_power_off` | `pile_id` | 关闭充电桩 |
| GET | `/api/set_pile_parameters` | 电价参数 | 在线调整电价 |
