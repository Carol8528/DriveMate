# V8 架构说明

V9 使用两个服务进程和一个前端进程，前端不承载业务编排：

1. React 前端通过 `frontend/server.mjs` 的同源代理调用 Agent API，Token 不进入浏览器脚本。
2. `backend_server.py` 负责本地 Bearer 鉴权、请求大小限制、路由和 HTTP 错误语义。
3. `backend_service.py` 负责运行生命周期及 V7 展示合同适配。
4. `components/semantic_understanding.py` 可调用外接 OpenAI-compatible LLM，仅生成意图、置信度与语义槽位；本地 IntentGraph 负责安全覆盖与融合。
5. `components/scenario_decomposer.py` 负责复杂场景拆解：当一句话同时包含多个目标、约束或授权动作（家庭长途出行、赶飞机行程、Robotaxi 临时下车）时，把它编译成带依赖关系的子目标 DAG；拆解结果不直接执行，仍交给下一条确定性链。
6. `components` 的 ConstraintShield、DependencyPlanner、ConfirmationGrant、SchemaValidator、ToolExecutor 完成确定性的权限裁决和执行。多阶段授权链（停车 → 状态重检 → 解锁）中，已确认执行的步骤在同一 Run 内复用回执，不会重放或重复挂起。
7. 车辆控制只能通过带独立令牌的 `simulator_server.py` 执行。

## 运行生命周期

`create` 会保存原始请求和快照，执行可立即执行的步骤，并把 L2 操作作为带 `grant_id` 的待确认项返回。`confirm` 使用新快照重新计算授权摘要；安全相关状态变化会使旧授权失效。`cancel` 只取消当前运行的待确认动作，不会误调用业务上的“取消订单”工具。

同一进程内的创建、确认和取消由锁串行化；同一 Run 内的相同成功副作用还会由 SQLite 幂等记录去重。

## 数据边界

- API 令牌和座舱令牌仅来自环境变量或一键启动时生成。
- REST 元数据不返回工具定义的本地 `source_path`。
- 审计下载会把 SQLite 中的 JSON 字符串解码成对象，但仍只允许持有本地 API 令牌的客户端读取。
- 前端演示传感器始终标记 `simulated=true`，不会伪装成真实车辆传感器。


## 外接模型边界

外接 LLM 不接收工具 schema，不参与 ToolExecutor，也不能创建授权。它的输出被视为不可信的概率性语义证据；若外接服务不可用，系统回退到本地 IntentGraph。高风险本地安全覆盖始终优先，最终动作仍必须经过硬约束、参数校验、确认授权、状态复核和审计。
