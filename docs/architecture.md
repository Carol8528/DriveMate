# V8 架构说明

V8 使用两个服务进程和一个前端进程，避免把业务编排重新耦合进 Streamlit：

1. Streamlit 前端只通过 `api_client.py` 调用 Agent API。
2. `backend_server.py` 负责本地 Bearer 鉴权、请求大小限制、路由和 HTTP 错误语义。
3. `backend_service.py` 负责运行生命周期及 V7 展示合同适配。
4. V6 的 `components` 完成意图识别、硬约束过滤、依赖编排、安全授权、执行恢复和审计。
5. 车辆控制只能通过带独立令牌的 `simulator_server.py` 执行。

## 运行生命周期

`create` 会保存原始请求和快照，执行可立即执行的步骤，并把 L2 操作作为带 `grant_id` 的待确认项返回。`confirm` 使用新快照重新计算授权摘要；安全相关状态变化会使旧授权失效。`cancel` 只取消当前运行的待确认动作，不会误调用业务上的“取消订单”工具。

同一进程内的创建、确认和取消由锁串行化；同一 Run 内的相同成功副作用还会由 SQLite 幂等记录去重。

## 数据边界

- API 令牌和座舱令牌仅来自环境变量或一键启动时生成。
- REST 元数据不返回工具定义的本地 `source_path`。
- 审计下载会把 SQLite 中的 JSON 字符串解码成对象，但仍只允许持有本地 API 令牌的客户端读取。
- 前端演示传感器始终标记 `simulated=true`，不会伪装成真实车辆传感器。
