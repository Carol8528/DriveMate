# 多模态演示样例

`multimodal_snapshot.json` 是提交仓库内可直接检查、可复用测试的结构化样例。它明确标记 `simulated: true`，用于验证 DMS、语音与车辆状态三类输入的融合契约，不冒充实车采集数据。

界面使用的路线图和座舱视觉资产位于 `assets/figma-hmi/`。若接入真实传感器，只需按 `schema_version` 提供同结构数据，并将来源、采集时间和模拟标志准确填写。
