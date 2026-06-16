# smart-charging-system666
软工大作业

# 智能充电桩调度计费系统 (Smart Charging System)

本项目为软件工程大作业（作业3系统实现阶段）的后端代码仓库。系统严格基于作业2设计的 **Django MTV + 前后端分离四层架构**（前端层 → 视图层 → 业务逻辑层 → 数据模型层）进行开发。

---

## 🛠️ 项目目录结构与全员分工


```text
smart-charging-system666/
│
├── backend/                  # ⚙️ 中央控制与全局配置（组长/E 维护）
│   ├── settings.py           # 全局配置（MySQL连接、DRF配置、全局变量）
│   └── urls.py               # 总路由（负责把前端请求分流给 views.py）
│
├── charging_system/          # 核心业务模块
│   │
│   ├── services/             # 📂 【业务逻辑层】（核心分工填空区）
│   │   ├── __init__.py       # 通行证，保持空白
│   │   ├── dispatch_service.py # 🧠 核心调度算法 【组长、B、D 负责】
│   │   ├── car_service.py      # 🚗 车辆状态与用户指令 【A、B 负责】
│   │   ├── pile_service.py     # ⚡ 充电桩管理与监控数据 【D、E 负责】
│   │   └── bill_service.py     # 💰 分时计费与账单引擎 【C 负责】
│   │
│   ├── models.py             # 💾 【数据模型层】车辆/桩/账单的字段定义 【C 优先完成】
│   ├── views.py              # 🔌 【视图层】接收前端HTTP请求并调用Service 【全员编写API】
│   ├── admin.py              # 🖥️ Django自带后台注册（演示故障场景用） 【C 注册】
│   └── tests.py              # 🧪 单元测试文件（前端没做好前，可在此写测试数据Debug）
│
└── manage.py                 # 项目管理入口脚本


