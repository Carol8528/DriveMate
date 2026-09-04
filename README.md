# DriveMate V9

DriveMate 是面向新能源车主与 Robotaxi 乘客的可审计车载智能体演示系统。项目将融合感知、意图理解、安全裁决、依赖编排、工具执行、状态回读和审计追踪放入同一套全栈闭环，并通过独立 React 前端展示完整过程。

> 当前仓库是 GOAI 复赛演示版本。车辆状态、DMS、语音及环境数据均为可复现的本地模拟数据，不代表已完成量产车、真实订单平台或真实传感器接入。

## 核心能力

- 双场景交互：支持“车主自驾”和“Robotaxi 乘客”两种身份与权限边界。
- 多模态融合：联合车辆、驾驶员、语音和环境快照生成可解释判断。
- 跨域任务编排：覆盖座舱舒适、导航充电、安全监测、Robotaxi 行程和人工应急等工具域。
- 风险确认：高风险写操作进入待确认状态；确认前重新校验关键状态，状态发生实质变化时拒绝沿用旧授权。
- 执行闭环：展示感知、理解、裁决、规划、执行和回读阶段，以及每一步的执行结果。
- 多轮会话：同一用户与模式可复用 Session，后端读取最近 8 轮历史上下文。
- 完整审计：每个 Run 保存计划、确认、工具回执、状态变化及本地知识引用。
- 可选百炼引擎：配置凭据后可启用百炼应用；其工具调用仍须经过本地安全、确认和审计边界。
- 单页 HMI：支持日间/夜间主题、语音输入、快捷场景、路线、座舱、融合感知、执行计划和主动安全视图。

## 系统架构

```text
React Web 前端（frontend/）
        │  同源 /api 代理，浏览器不接触 API Token
        ▼
Agent REST API（backend_server.py）
        ▼
业务编排服务（backend_service.py）
        ├─ IntentGraph / 本地知识检索
        ├─ ConstraintShield / SchemaValidator
        ├─ DependencyPlanner / SafetyGuard
        ├─ ConfirmationGrant / RecoveryMesh
        ├─ ToolExecutor / VehicleGateway
        └─ SQLite Audit / Session
                         │
                         ▼
              座舱模拟器（simulator_server.py）
```

前端只向同源服务发送请求。`frontend/server.mjs` 在服务端加入 Bearer Token 后转发给 Agent API，因此令牌不会下发到浏览器。

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 20.19+（或 22.12+）
- npm

### 打开前端页面

在 Windows 中打开 PowerShell，进入项目根目录

首次运行时安装 Python 和前端依赖：

```powershell
python -m pip install -r requirements.txt
npm --prefix frontend ci
```

依赖安装完成后，启动完整演示：

```powershell
python start_demo.py
```

`start_demo.py` 会自动生成本次运行使用的随机令牌，依次启动座舱模拟器、Agent API 和 React 前端，并在浏览器中打开 DriveMate。以后再次运行时，通常只需进入项目根目录并执行 `python start_demo.py`，无需重复安装依赖。

如果浏览器没有自动打开，可手动访问 [http://127.0.0.1:8501](http://127.0.0.1:8501)。运行期间不要关闭 PowerShell 窗口；需要停止全部服务时，在该窗口按 `Ctrl+C`。

> 不要直接双击 `frontend/index.html`。前端页面依赖 Agent API 和座舱模拟器，应通过 `start_demo.py` 启动完整服务。

| 服务 | 默认地址 |
|---|---|
| Web 前端 | `http://127.0.0.1:8501` |
| Agent API | `http://127.0.0.1:8000` |
| 座舱模拟器 | `http://127.0.0.1:8765` |

若默认端口已占用，一键启动脚本会自动选择本机可用端口，此时请以 PowerShell 窗口输出的实际前端地址为准。本地数据写入 `data/*.db`，这些数据库已被 Git 忽略。

## 使用方式

1. 在顶部切换“车主自驾”或“Robotaxi”。
2. 通过快捷场景、键盘或浏览器语音识别输入需求。
3. 在主视图区查看路线、座舱状态、融合感知、执行计划和安全结论。
4. 遇到待确认操作时选择“确认执行”或“取消”。
5. 在审计区域查看或下载当前 Run 的完整审计链。

推荐演示场景包括疲劳驾驶安全处置、带孩子出行的座舱调整、路线导航，以及 Robotaxi 行程状态查询和安全上下车点处理。

## 配置

一键启动无需创建 `.env`。如需启用外部引擎、固定端口或分开启动服务，可复制 `.env.example` 并按需配置。不要提交真实密钥。

| 环境变量 | 用途 | 是否必需 |
|---|---|---|
| `DRIVEMATE_API_TOKEN` | Agent API Bearer Token | 分开启动时必需 |
| `DRIVEMATE_SIMULATOR_TOKEN` | 座舱模拟器 Bearer Token | 分开启动时必需 |
| `DRIVEMATE_BACKEND_URL` | 前端代理访问的后端地址 | 可选，默认 `http://127.0.0.1:8000` |
| `DRIVEMATE_SIMULATOR_URL` | 后端访问的模拟器地址 | 可选，默认 `http://127.0.0.1:8765` |
| `DRIVEMATE_FRONTEND_URL` | 一键启动使用的前端地址 | 可选，默认 `http://127.0.0.1:8501` |
| `DRIVEMATE_AUDIT_DB` | 审计数据库路径 | 可选 |
| `DRIVEMATE_SIMULATOR_DB` | 模拟器状态数据库路径 | 可选 |
| `DRIVEMATE_APP_ID` | 百炼应用 ID | 启用百炼时必需 |
| `DASHSCOPE_API_KEY` | DashScope API Key | 启用百炼时必需 |
| `CRM_API_ENDPOINT` / `CRM_API_KEY` | 外部 CRM 人工接管接口 | 可选 |

仅当 `DRIVEMATE_APP_ID` 与 `DASHSCOPE_API_KEY` 同时存在时，前端才会显示“百炼应用（App API）”选项。

## 分开启动

```powershell
$env:DRIVEMATE_SIMULATOR_TOKEN="<随机令牌>"
$env:DRIVEMATE_API_TOKEN="<另一随机令牌>"
$env:DRIVEMATE_API_MODE="http"
$env:DRIVEMATE_SIMULATOR_URL="http://127.0.0.1:8765"
$env:DRIVEMATE_BACKEND_URL="http://127.0.0.1:8000"

# 分别在三个终端运行
python simulator_server.py
python backend_server.py
npm --prefix frontend run build
npm --prefix frontend start
```

前端进程必须能够读取 `DRIVEMATE_BACKEND_URL` 和 `DRIVEMATE_API_TOKEN`，由本地代理安全转发请求。

## REST API

Agent API 接口要求以下请求头：

```http
Authorization: Bearer <DRIVEMATE_API_TOKEN>
```

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 查询 API、审计库和模拟器状态 |
| `GET` | `/api/v1/meta` | 查询模式、引擎和脱敏工具元数据 |
| `POST` | `/api/v1/agent/runs` | 创建一次 Agent Run |
| `POST` | `/api/v1/agent/runs/{run_id}/confirm` | 使用最新状态快照确认待执行操作 |
| `POST` | `/api/v1/agent/runs/{run_id}/cancel` | 取消待确认操作 |
| `GET` | `/api/v1/simulator/state` | 读取座舱模拟状态 |
| `GET` | `/api/v1/audit/runs/{run_id}` | 获取完整审计链 |

Run 状态包括 `completed`、`waiting_confirmation`、`degraded`、`failed` 和 `cancelled`。首次请求无需传入 `session_id`；响应返回 Session 后，后续请求可回传该 ID 继续多轮会话。服务端会校验 Session 的用户和模式，避免跨用户或跨模式串话。

## 项目结构

| 路径 | 内容 |
|---|---|
| `frontend/` | React HMI、唯一正式样式、同源 API 代理 |
| `backend_server.py` | REST 路由、鉴权和请求边界 |
| `backend_service.py` | Agent 运行、确认、取消、会话和响应适配 |
| `simulator_server.py` | 可鉴权的本地座舱模拟器 |
| `components/` | 编排、安全、执行、恢复和审计组件 |
| `tools/` | 按业务域分类的工具 Schema 与元数据 |
| `knowledge/` | 可检索、可引用的本地 Markdown 知识库 |
| `assets/` | 前端图片与地图素材 |
| `data/samples/` | 多模态数据契约样例 |
| `tests/` | 后端、API、安全授权、模拟器和前端合同测试 |
| `scripts/` | 架构与端到端验证脚本 |
| `docs/` | 架构、设计、合规和 GitHub 上传说明 |

更多资料见 [项目文档索引](docs/README.md)、[系统架构](docs/architecture.md)、[数据来源与合规边界](docs/data-source-and-compliance.md) 和 [GitHub 上传清单](docs/github-upload-checklist.md)。

## 验证

```powershell
python -m unittest discover -s tests -t .
python scripts/architecture_validation.py
python scripts/e2e_validation.py
npm --prefix frontend run build
```

端到端验证通过真实 REST API 依次经过意图理解、约束校验、依赖编排、工具执行、座舱状态回读和 SQLite 审计下载。验证结果写入 Git 已忽略的 `.artifacts/validation/`。

多模态样例位于 [`data/samples/multimodal_snapshot.json`](data/samples/multimodal_snapshot.json)。它用于核验 DMS、语音、车辆总线和环境数据契约，不等同于实车采集证据。

## 能力边界

- 当前所有车辆与订单操作均在本地模拟器中执行。
- 浏览器语音输入依赖浏览器自身的 Web Speech API 支持与权限。
- 外部百炼和 CRM 能力只有在用户自行配置有效凭据后才会启用。
- 当前指标是固定演示场景和自动化测试口径，不应解释为量产业务效果。
- 实车接入、功能安全、网络安全、隐私合规和车型适配仍需独立验证与认证。

## 开源与贡献

项目采用 [Apache License 2.0](LICENSE)。贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题提交方式见 [SECURITY.md](SECURITY.md)，第三方依赖与素材边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
