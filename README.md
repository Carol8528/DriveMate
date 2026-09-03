# DriveMate V8 复赛提交版

V8 将 **V6 的可审计决策后端** 与 **V7 的新版 Streamlit 前端** 合并为一套可独立运行的全栈演示。默认通过真实本地 REST 接口联调，不再以 Mock 数据冒充后端执行。

## 目标用户与核心痛点

DriveMate 面向两类用户：驾驶中的新能源车主，以及 Robotaxi 行程中的乘客。现有车机助手常见问题是单轮指令割裂、跨域服务需要反复操作、高风险动作缺少确认、工具调用结果不可追溯；无人驾驶乘客还会遇到找车、改点、身体不适和人工求助入口分散的问题。

本项目用统一状态快照、跨轮 Session、硬约束安全门、依赖编排与执行回读，把“理解需求—生成方案—确认高风险动作—执行—审计”闭环放进同一交互界面。

## 量化收益与推广预期

以下是复赛阶段的**验收目标**，不是已取得的量产业务结果：

| 指标 | 当前可验证口径 | 推广目标 |
|---|---|---|
| 核心演示任务成功率 | 由 `scripts/e2e_validation.py` 对固定场景逐次计算 | 固化为发布门禁，保持 100% 固定场景通过 |
| 高风险误执行 | L2/L3 写操作必须经过确认授权，自动化测试覆盖 | 固定场景中保持 0 次未授权执行 |
| 可追溯性 | 每个 Run 保存计划、工具回执、确认和工单 | 核心场景审计链覆盖率 100% |
| 多轮连续性 | 同一用户与模式复用 Session，并回读最近 8 轮 | 减少用户重复陈述，后续以用户测试统计轮次降幅 |

推广分三步：先用于展厅/赛事的可复现演示；再与车企座舱网关、订单系统和客服沙箱联调；最后在完成隐私、安全、法规和实车验证后进入受控试点。真实节省时间、转人工率和满意度需在试点中采集，当前不作未经验证的商业承诺。

## 一键运行

```powershell
python -m pip install -r requirements.txt
python start_demo.py
```

`start_demo.py` 会依次启动：

1. 带一次性鉴权令牌的座舱模拟器；
2. 带一次性鉴权令牌的 Agent REST API；
3. 已切换到 HTTP 模式的 V8 Streamlit 前端。

运行数据只写入本地 `data\*.db`，不会提交到版本库。

## 架构

```text
app.py + api_client.py
        │  REST + Bearer Token
        ▼
backend_server.py
        ▼
backend_service.py
        ├─ IntentGraph
        ├─ ConstraintShield
        ├─ Dependency Planner
        ├─ SafetyGuard / ConfirmationGrant
        ├─ RecoveryMesh
        └─ SQLite Audit
                 │
                 ▼
          simulator_server.py
```

- `app.py`、`ui_chrome.py`、`perception_fusion.py`、`assets\`：V7 有效前端。
- `backend_server.py`：V8 REST 边界、请求校验与鉴权。
- `backend_service.py`：从 V6 UI 中抽离的无界面运行、确认、取消和结果适配。
- `components\`、`tools\`：V6 决策、安全、执行和工具定义。
- `simulator_server.py`：V6 可验证座舱执行器。
- `tests\`：后端、API、确认授权、模拟器与 V7 布局合同测试。

未纳入 V8 的内容包括 `.venv`、`__pycache__`、SQLite/WAL 运行数据、测试临时输出、审计截图、旧版前端及未被运行时引用的重复图片。

## 目录结构

| 路径 | 内容 |
|---|---|
| `app.py`、`api_client.py`、`ui_chrome.py`、`perception_fusion.py` | Streamlit 前端与 API 适配 |
| `backend_server.py`、`backend_service.py`、`simulator_server.py` | Agent API、业务服务与座舱模拟器 |
| `components\` | 编排、安全、确认、执行、恢复与审计组件 |
| `tools\` | 按业务域分类的工具定义 |
| `assets\` | 前端图片、地图和样式 |
| `tests\` | 自动化测试 |
| `scripts\` | 架构、端到端和设计规范验证脚本 |
| `docs\` | 架构、设计、历史归档和 GitHub 上传清单 |
| `prompts\` | 系统提示词 |
| `knowledge\` | 随仓库交付、可检索并可引用的 Markdown 知识库 |
| `data\` | 本地运行数据；数据库文件不会提交 |

详细文档见 [`docs\README.md`](docs/README.md)，上传前请检查
[`docs\github-upload-checklist.md`](docs/github-upload-checklist.md)。

## REST API

所有接口都要求：

```http
Authorization: Bearer <DRIVEMATE_API_TOKEN>
```

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | API、审计库和座舱模拟器状态 |
| `GET` | `/api/v1/meta` | 模式、可用引擎和脱敏工具信息 |
| `POST` | `/api/v1/agent/runs` | 创建运行 |
| `POST` | `/api/v1/agent/runs/{run_id}/confirm` | 以新状态快照确认待执行操作 |
| `POST` | `/api/v1/agent/runs/{run_id}/cancel` | 取消本次运行的待确认操作 |
| `GET` | `/api/v1/simulator/state` | 读取已验证的座舱状态 |
| `GET` | `/api/v1/audit/runs/{run_id}` | 下载已解码的完整审计链 |

前端要求 Run 响应包含 `run_id`、`intent`、`reply`、`risk_level`、`plan_summary`、`steps`、`safety_tip`、`calls`、`pending_tools`、`perception_fusion` 和 `action_outcome`。V8 后端统一补齐这些字段，并明确标记 `completed`、`waiting_confirmation`、`degraded`、`failed` 或 `cancelled`。

第一次创建 Run 时不传 `session_id`，响应会返回新 Session；后续请求回传该 `session_id` 即可复用最近 8 轮用户输入、回复与意图。服务端会校验 Session 的用户和模式，拒绝跨用户或跨模式串话。响应中的 `session_context` 给出实际使用的历史轮数，`knowledge_refs` 给出本轮命中的本地知识文件。

## 分开启动

先设置同一组令牌，再分别启动三个进程：

```powershell
$env:DRIVEMATE_SIMULATOR_TOKEN="<随机令牌>"
$env:DRIVEMATE_API_TOKEN="<另一随机令牌>"
$env:DRIVEMATE_API_MODE="http"

python simulator_server.py
python backend_server.py
python -m streamlit run app.py
```

仅需预览前端布局时可显式设置：

```powershell
$env:DRIVEMATE_API_MODE="mock"
python -m streamlit run app.py
```

Mock 模式会清楚标注为预览，不执行车辆或订单动作。

## 百炼应用

设置 `DRIVEMATE_APP_ID` 与 `DASHSCOPE_API_KEY` 后，后端才会在 `/api/v1/meta` 中声明“百炼应用”引擎，前端随后显示该选项。百炼提出的本地工具调用仍会经过 V6 的 SchemaValidator、ConstraintShield、SafetyGuard、确认授权和审计链，不能绕过本地安全边界。

## 验证

```powershell
python -m unittest discover -s tests -t .
python scripts\architecture_validation.py
python scripts\e2e_validation.py
python scripts\check_design_compliance.py
```

`scripts\e2e_validation.py` 不直接调用工具执行器。它从 Streamlit 使用的
`HttpBackendClient` 发起请求，完整经过 Agent REST API、IntentGraph、
ConstraintShield、依赖编排、工具执行、座舱状态回读和 SQLite 审计下载。
高疲劳场景中的人工转接与 CRM 接管由规则计划自动触发，导航仍须单独确认。
量化结果写入 `.artifacts\validation\e2e_validation.md` 和
`.artifacts\validation\e2e_validation.json`。

多模态数据目前仍是明确标识的可复现演示输入，并非实车采集。仓库提供实际样例文件 [`data/samples/multimodal_snapshot.json`](data/samples/multimodal_snapshot.json)，用于核验 DMS、语音和车辆总线数据契约；接入量产传感器不在本提交版能力声明内。

## 开源与贡献

项目采用 [Apache License 2.0](LICENSE)。贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，直接依赖及素材边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
