# smart-charging-system666
软工大作业

# 智能充电桩调度计费系统（后端）团队开发与协作规范指南

##  系统当前目录结构规范

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
🚀 二、 剩余工作与整合全栈分工
后端残余业务逻辑函数（修改电量/硬启停）由相关人员自行顺手补齐。剩余核心工作全面聚焦于 Views 接口管道封装 与 两个极简前端网页的开发与联调：

🚗 1. 车主端全栈流线 —— 【组员 A 与 组员 C 共同承包】
Views 接口化：在 views.py 中编写对应视图，用 request.GET.get('car_id') 接收车牌号，调用 Service 函数后用 JsonResponse(data) 将车辆数据返回给前端。

极简网页开发 (client.html) —— 组员 C 主导：

页面布局：纯静态 HTML。上半部分为原生表单（输入框：输入车牌号；下拉框：选择快慢充模式、输入目标电量；按钮：【提交充电请求】、【中途修改】、【取消充电】）。下半部分放几行原生文本标签用于显示状态。

核心逻辑：使用 setInterval 开启一个 每 2 秒 的定时器，自动执行 axios.get 请求后端的 Query_Charging_State 接口。拿到 JSON 数据后，直接用 JavaScript 动态刷新文本内容，实现已充电量、当前账单金额在网页上的丝滑跳动。充电结束后弹窗渲染最终费用详单。

⚡ 2. 管理大屏与基础管控全栈流线 —— 【组员 D 与 组员 E 共同承包】
Views 接口化：在 views.py 中将大屏监控数据（Query_PileState, Query_QueueState）及故障触发函数封装为标准的 HTTP JSON 接口。

极简网页开发 (admin_dashboard.html) —— 组员 E 主导：

页面布局：纯静态 HTML。坚决不画图表，直接堆 2 个基础 HTML 表格（<table>）：

表格①（充电桩资产看板）：展示 5 个桩的 ID、类型、当前状态（空闲/充电/故障）。最后放一个 <button> 按钮写着“模拟故障”，点击直接触发 axios 请求后端的 handle_pile_fault 接口。

表格②（实时排队详情）：展示各个桩后方专属队列里正在排着的车辆车牌号列表（上限 4 辆）。

核心逻辑：页面加载时开启一个 每 1 秒 的定时器，全量轮询后端接口并重新渲染这两个表格。随堂验收演示时，只要点击表格①的“模拟故障”红按钮，评委老师就能在 1 秒内看到表格②里的排队车辆被后端调度算法自动流转到其他正常桩表格里的全自动过程！


三、 协作开发工作流纪律
分支代码强制同步：鉴于底层数据库模型与核心调度文件已更新推送，所有组员在开始各自的残余模块编写前，必须先在终端运行 git pull，随后必须执行 python manage.py migrate 同步本地数据库，以杜绝因模型不一致引发的运行时异常。

跨域联调设置：前端同学编写本地 .html 静态页面时，Axios 的请求基地址直接指向组长运行后端服务器的局域网 IP。后端已完成跨域资源共享（CORS）配置，联调接口无阻碍。
