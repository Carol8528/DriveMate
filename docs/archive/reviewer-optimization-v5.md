# V5 + test-main 融合评审版说明（历史归档）

> 本目录已在原 V5 的真实执行/安全/审计底座上，整合 IntentGraph、ConstraintShield、真实工具 DAG、ConfirmationGrant、RecoveryMesh 与决策账本。

> 本文仅用于保留 V5 阶段的评审背景，文件名、命令和指标不代表当前 V8
> 实现。当前使用方法以仓库根目录 `README.md` 为准；文中的凭据示例已全部替换。


本版本针对评委提出的五项意见进行收敛式改造，目标不是继续扩功能，而是让“执行、安全、审计、端到端验证”可以被现场复核。

## 1. 解决“模拟执行/伪造记录”

原版本的座椅、空调、媒体、导航等由 Streamlit 内部 Mock 直接返回“成功”，调用耗时也由随机数生成。V5 改为：

- 新增独立进程 `simulator_server.py`，作为车机/座舱模拟器；
- Streamlit 通过 `components/vehicle_gateway.py` 以 HTTP 调用模拟器；
- 已接入并可二次查询状态的控制接口：
  - `set_climate` → `/v1/cabin/climate`
  - `set_seat` → `/v1/cabin/seat`
  - `play_media` → `/v1/cabin/media`
  - `set_ambient` → `/v1/cabin/ambient`
  - `plan_route` → `/v1/navigation/route`
  - `contact_vehicle` → `/v1/vehicle/contact`
- 每次成功执行返回唯一 `receipt_id`，并把状态写入模拟器 SQLite；前端可通过 `/v1/state` 再次查询验证；
- 删除随机耗时和“根据计划补造成功工具调用”的逻辑。没有执行回执时，UI 不允许把步骤标成“已执行”。

> 这是**独立座舱模拟器接口**，不是量产车辆接口。它满足评委所说的“真实接口或车机/座舱模拟器”的第二类要求，并把前端 Mock 与执行后端真正分离。

## 2. 修复安全校验与鉴权缺口

### 2.1 L0–L3 硬安全闸门

`components/safety_guard.py` 在工具执行前统一校验：

- 车主/Robotaxi 模式权限；
- **所有 L2 操作强制确认**，不能依赖 LLM 是否正确判断；
- `contact_vehicle` 在执行层用乘客、车辆经纬度计算 Haversine 距离；
- 距离缺失或超过 100m 时直接拒绝，不再使用随机距离；
- 安全失败记录也进入审计链。

工具元数据同时修正：`find_rest_area`、`find_charging_station` 作为只读查询降为 L0；`plan_route` 明确为 L2 且 `requires_confirmation=true`。

### 2.2 鉴权与密钥

- 删除源码中的百炼 App ID/API Key 硬编码；
- 仅从 `DRIVEMATE_APP_ID`、`DASHSCOPE_API_KEY` 等环境变量读取；
- 座舱模拟器所有接口均要求 Bearer Token；
- `start_demo.py` 每次启动自动生成一次性随机 Token，并同时注入 Streamlit 与模拟器，不把 Token 写入源码；
- 错误 Token 的自动测试必须返回 HTTP 401。

**重要：原始 V4 中出现过源码硬编码的 API Key。该 Key 应视为已经暴露，建议立即在对应控制台撤销/轮换；V5 不再包含该 Key。**

## 3. 持久化审计与可追溯闭环

新增 `components/audit_store.py`，使用 SQLite 持久化：

- `sessions`：会话；
- `runs`：每次用户任务；
- `tool_calls`：工具、参数、结果、后端、真实 HTTP 时延、执行回执；
- `confirmations`：用户确认/取消；
- `tickets`：转人工工单。

每个任务都有 `Run ID`。Streamlit 页面可直接展开“持久化审计链”，并下载该 Run 的 JSON，能够回溯：

`用户请求 → 风险等级 → 待确认 → 用户确认 → 工具执行 → 回执 → 转人工工单`

## 4. 单一真实场景端到端验证

验证脚本：

```bash
python scripts\e2e_validation.py
```

测试场景固定为：

`司机疲劳 → L3 风险 → DMS/安全建议 → 空调/按摩/音乐由独立座舱模拟器执行 → 导航确认前被阻止 → 用户确认 → 导航执行 → 必要时转人工并落库`

验证结果会生成到 `.artifacts\validation\e2e_validation.md` 和
`.artifacts\validation\e2e_validation.json`，该目录不会提交到版本库：

- 10 次场景运行，10 次成功；
- 任务成功率：100%；
- HTTP 控制调用 40 个样本；
- 平均时延约 4.98 ms；
- P95 约 8.14 ms；
- 错误 Bearer Token：成功拒绝；
- 闪灯鸣笛 161.7m：成功阻止；
- 闪灯鸣笛 33.4m：确认后成功执行。

这些数字是**本机独立模拟器**数据，不应表述为真实量产车辆网络/ECU 性能。评审现场可以重新运行脚本生成新的测量结果。

## 5. 拆分 Streamlit 高耦合模块

原 `appv4.py` 同时承担 UI、规则编排、工具执行、安全、CRM、工具注册、密钥配置等职责。V5 已拆分为：

```text
appv4.py                     Streamlit UI + LLM 应用调用适配
components/config.py         环境变量配置
components/tool_registry.py  tools/**/*.json 注册
components/rule_engine.py    本地规则编排
components/safety_guard.py   模式/L2确认/100m距离硬校验
components/tool_executor.py  统一执行入口与审计
components/vehicle_gateway.py HTTP 座舱执行网关
components/audit_store.py    SQLite 审计
components/crm_agent.py      转人工/CRM 工单
simulator_server.py          独立座舱模拟器
prompts/system_prompt.md      百炼系统提示词备份
scripts/e2e_validation.py    端到端验证与量化指标
```

`appv4.py` 已从约 1477 行下降到约 800 行，后端执行、安全、审计与规则逻辑不再直接耦合到 Streamlit。

## 一键启动 Demo

### Windows 11 / PowerShell

```powershell
$env:DRIVEMATE_APP_ID="<your_bailian_app_id>"
$env:DASHSCOPE_API_KEY="<your_dashscope_api_key>"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python start_demo.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python start_demo.py
```

`start_demo.py` 会：

1. 运行时生成一次性随机 Bearer Token；
2. 默认选择本机动态空闲端口，避免残留旧模拟器占用 8765；
3. 启动独立座舱模拟器，并循环执行带 Bearer Token 的 `/health` 鉴权握手；
4. 只有收到 `authenticated=true` 后才启动 Streamlit；
5. Streamlit 退出后自动关闭本次模拟器。

因此演示时不要分别手工启动 `simulator_server.py` 和 `streamlit run appv4.py`。直接使用 `python start_demo.py`，可保证前端与模拟器共享同一个运行时 Token。若侧边栏显示“Bearer Token 不一致”，通常说明存在旧模拟器进程或手工启动时两端环境变量不一致；关闭旧进程后重新执行一键启动即可。

页面默认使用“融合编排引擎（本地可审计）”，不需要任何云端 API Key。若需要演示百炼 LLM，再设置：

不要把真实密钥写回 Python 文件。

## 推荐评审演示顺序

1. 启动 `python start_demo.py`，侧边栏应显示“独立座舱模拟器：已鉴权连接”。
2. 点击“疲劳驾驶”预设并运行。
3. 展开工具调用记录：座椅按摩、媒体等应出现 `backend=simulator_http` 和 `receipt_id`。
4. 展开“座舱模拟器当前状态”：验证 `seat.active=true`、`media.playing=true`。
5. 页面应显示导航 `pending_confirm`；点击确认后，导航才出现成功回执。
6. 展开“持久化审计链”：查看确认、工具调用及工单记录，并导出 JSON。
7. 展开“端到端量化验证”展示成功率/时延。
8. Robotaxi 模式下调整乘客/车辆经纬度：>100m 时即使确认，闪灯鸣笛也应被安全层拒绝；<100m 才可执行。