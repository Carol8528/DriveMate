# DriveMate V9 Web 前端规范

## 唯一正式实现

- `frontend/src/App.jsx`：页面状态、三栏组件和交互入口。
- `frontend/src/api.js`：浏览器端唯一 API 调用层。
- `frontend/src/styles.css`：唯一正式样式与响应式规则。
- `frontend/server.mjs`：静态资源服务与本地鉴权代理；API Token 不进入浏览器。
- `assets/figma-hmi/`：正式图片和地图素材。

旧 Streamlit 页面、`views/`、DOM 桥接样式和对应测试已删除，不得恢复或并行维护。

## 页面结构

桌面端采用一层顶部栏与一层三栏工作区：驾驶舱 30%、智能中控 45%、Agent 25%。中控包含导航、座舱控制、融合感知、服务编排、安全评估和指令记录六个互斥视图。同一时间只渲染一个中控视图，不复制页面容器。

## 修改约束

1. 颜色、面板、边框、阴影和圆角优先复用 `:root` 变量。
2. 同一组件只保留一个选择器和一个实现，修改后删除被替代规则。
3. 不使用 `!important`、负边距或父子容器重复背景修补布局。
4. API 调用只能通过 `api.js`；不得在前端代码中写入 Token。
5. Agent 返回的 `state_diff` 是车辆预览状态的唯一回写来源。
6. 高风险动作必须显示确认或取消入口，不得由前端绕过授权。

## 验收

- `npm --prefix frontend run build` 必须通过。
- `python -m unittest discover -s tests -t .` 必须通过。
- 1280×720 与 1366×768 必须使用原生浏览器截图检查一屏展示、比例、遮挡和截断。
- 必须回归 Enter、快捷操作、语音输入降级、语音播报、Toast、确认/取消、状态回写和审计下载。
