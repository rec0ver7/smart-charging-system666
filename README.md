# smart-charging-system666
软工大作业

# 智能充电桩调度计费系统（后端）团队开发与协作规范指南

## 一、 系统当前目录结构规范

系统核心工程目录已于 Git 远端完成初始化，整体架构层级与文件分布如下：

```text
smart-charging-system666/
│
├── backend/                             # 【中央控制层】项目全局配置
│   ├── __init__.py
│   ├── settings.py                      # 数据库连接、全局变量、第三方插件注册
│   ├── urls.py                          # 总路由映射：负责将前端请求分流至 views.py
│   └── ...
│
├── charging_system/                     # 核心业务子应用根目录
│   │
│   ├── migrations/                      # 🗂️ 【数据库变动日志】由 Django 自动维护
│   │   └── __init__.py                  # 迁移初始化文件（当前仅有此文件，禁止手动修改）
│   │
│   ├── services/                        # 📂 【业务逻辑层】核心算法与业务计算包
│   │   ├── __init__.py                  # 包引导通行证，保持空白
│   │   ├── dispatch_service.py          # 🧠 排队调度与突发故障恢复业务逻辑
│   │   ├── car_service.py               # 🚗 车辆状态控制、车主多指令业务逻辑
│   │   ├── pile_service.py              # ⚡ 充电桩生命周期管理、监控大屏数据源逻辑
│   │   └── bill_service.py              # 💰 尖峰平谷时段计费引擎与账单生成逻辑
│   │
│   ├── __init__.py                      # 应用引导通行证，保持空白
│   ├── admin.py                         # 🖥️ Django 内置管理后台注册单（位于 services 外）
│   ├── apps.py                          # 应用基础配置文件（位于 services 外）
│   ├── models.py                        # 💾 【数据模型层】核心对象实体类与数据库字段定义（位于 services 外）
│   ├── tests.py                         # 🧪 单元测试文件（位于 services 外）
│   └── views.py                         # 🔌 【接口视图层】接收 HTTP 请求并向前端返回 JSON 响应（位于 services 外）
│
├── .gitignore                           # Git 忽略文件（已配置，禁止改动）
├── manage.py                            # Django 工程管理入口脚本
└── README.md                            # 远端代码仓库主页说明文档

```




# ⚡ 智能充电桩调度计费系统 —— 敏捷开发进度与分工指南

## 🟢 一、 保留原始开发分工与最新完成情况

### 1. 数据模型与计费模块 —— 【组员 C 优先开工】

* **负责文件**：`charging_system/models.py`、`charging_system/services/bill_service.py`、`charging_system/admin.py`
* **具体落实动作**：
* `models.py`（使用 Django ORM 定义 Car、ChargePile、Bill 三个核心实体类） —— **【🟢 100% 已完成】**
* `admin.py`（将上述三个类注册至 Django Admin，确保能通过后台修改充电桩状态模拟突发故障） —— **【🟢 100% 已完成】**
* `bill_service.py`（编写 `Request_Bill()` 与 `Request_DetailedList()`；实现“尖峰平谷”多时段分时计费规则引擎算法；加入时间缩放系数） —— **【🟢 100% 已完成】**



### 2. 中央调度算法模块 —— 【组长、组员 B、组员 D 协同】

* **负责文件**：`charging_system/services/dispatch_service.py`
* **具体落实动作**：
* **组长**：编写 `E_chargingRequest()` 核心叫号分配接口；编写正常状态下的优先级调度算法；编写处理多车同桩排队的时间片轮询算法。 —— **【🟢 100% 已完成】**
* **组员 D**：编写时间顺序调度算法，确保在特定或故障模式下严格基于时间戳的公平排队与桩位分配逻辑。 —— **【🟢 100% 已完成】**
* **组员 B**：编写 `handle_pile_fault(fault_pile_id)` 函数，实现充电桩突发故障时的车辆提取与无缝重调度恢复逻辑。 —— **【🟢 100% 已完成】**



### 3. 车辆指令与状态维护模块 —— 【组员 A、组员 B 协同】

* **负责文件**：`charging_system/services/car_service.py`
* **具体落实动作**：
* **组员 A**：编写 `Modify_Amount(car_id, new_amount)` 支持中途修改目标充电量；编写 `Modify_Mode(car_id, new_mode)` 支持中途切换快慢充模式。 —— **【🔴 暂未完成】**
* **组员 B**：编写 `Start_Charging(car_id)` 控制车辆上桩；编写 `End_Charging(car_id)` 实现充满或主动取消的停止逻辑与计费结算；编写 `Query_Charging_State(car_id)` 实时返回当前已充度数与瞬时费用。 —— **【🟢 100% 已完成】**



### 4. 充电桩管理与监控模块 —— 【组员 D、组员 E 协同】

* **负责文件**：`charging_system/services/pile_service.py`
* **具体落实动作**：
* **组员 D**：编写 `powerOn(pile_id)` 与 `powerOff(pile_id)` 硬启停控制；编写 `setParameters()` 在线调整电价参数；编写 `Start_ChargingPile(pile_id)` 激活状态机。 —— **【🔴 暂未完成】**
* **组员 E**：编写 `Query_PileState()` 收集5个充电桩运行指标；编写 `Query_QueueState()` 获取专属队列车辆列表。 —— **【🔴 暂未完成】**



---

## ⏳ 二、 剩余工作与整合全栈分工

前端整体工作量轻量，本着“谁开发、谁联调、合并不分细”的原则，剩余的后端残余函数、Views 接口封装、以及极简 HTML 网页开发将直接打包归拢：

### 🚗 1. 车主端全栈流线 —— 【组员 A 与 组员 C 共同承包】

* **后端功能补齐**：由 **组员 A** 补齐 `car_service.py` 中修改充电量和切换模式的两个残余函数。
* **接口与网页交付**：由 **组员 C** 牵头，会同 **组员 A** 将车主端所有 Service 函数在 `views.py` 中包装为 JSON 接口。随后由 **组员 C** 编写极简静态网页 `client.html`（纯原生表单提交请求，配合定时器每 2 秒自动轮询刷新车辆当前状态与实时账单文字）。

### ⚡ 2. 管理大屏与基础管控全栈流线 —— 【组员 D 与 组员 E 共同承包】

* **后端功能补齐**：由 **组员 D** 补齐 `pile_service.py` 中管理员对桩的硬启停、调整参数等基础控制函数。
* **接口与网页交付**：由 **组员 E** 牵头，会同 **组员 D** 将管理员端所有的状态查询、队列查询、模拟故障函数在 `views.py` 中包装为 JSON 接口。随后由 **组员 E** 编写极简大屏网页 `admin_dashboard.html`（无需复杂图表，用 2 个基础 HTML 表格展示 5 个桩的状态及专属队列车辆列表，配合定时器每秒自动刷新，并在桩旁设置红色的“模拟故障”触发按钮）。

### 📝 3. 团队技术报告与文档汇总 —— 【组员 E 主撰，组员 B 协同】

* 项目整体联调完毕后，由 **组员 E** 负责主撰、**组员 B** 协助，将全系统的 Django 数据库设计字段表、分时计费积分公式、中央调度状态机切换图以及前端轮询机制说明，统一汇总整合成大作业最终提交的 Word 技术报告。

---

## 📅 三、 全员协作开发工作流纪律

1. **本地数据库强制同步**：鉴于底层模型与调度文件已更新推送，全员在动工前必须先执行 `git pull origin main`，随后在本地终端执行 `python manage.py migrate` 同步数据库地基，避免运行时报错。
2. **前后端接口联调**：前端编写静态网页时，无需配置复杂的单页面开发环境，Axios 的请求基地址直接指向后端运行服务器的局域网 IP。后端已配置放开 CORS 跨域限制，管道一接即通。
