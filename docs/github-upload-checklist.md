# GitHub 上传整理清单

## 已完成

- [x] 根目录仅保留项目入口、运行模块和 GitHub 常规配置文件。
- [x] 设计与架构文档统一放入 `docs\`。
- [x] 历史评审说明归档到 `docs\archive\`，并移除明文凭据。
- [x] 架构、端到端和设计校验脚本统一放入 `scripts\`。
- [x] 验证产物改写入 Git 忽略的 `.artifacts\validation\`。
- [x] SQLite、虚拟环境、缓存、日志、IDE 配置和内部材料已加入忽略规则。
- [x] `.gitattributes` 已统一文本文件行尾，避免跨平台无效差异。
- [x] 评委邮件移入本地 `private\`，不会被 Git 收录。
- [x] README、测试和脚本中的移动路径已同步更新。
- [x] 文本源码和文档已复扫，未发现残留的常见明文密钥格式。
- [x] 40 项单元测试、7 项架构验证、10 轮端到端场景和设计规范检查均已通过。

## 目录分类

| 分类 | 路径 | 是否上传 |
|---|---|---|
| 项目说明与安全策略 | `README.md`、`SECURITY.md` | 是 |
| 前端与 API 适配 | `app.py`、`api_client.py`、`ui_chrome.py`、`perception_fusion.py` | 是 |
| 后端与启动入口 | `backend_server.py`、`backend_service.py`、`simulator_server.py`、`start_demo.py` | 是 |
| 核心组件与工具定义 | `components\`、`tools\` | 是 |
| 静态资源与提示词 | `assets\`、`prompts\` | 是 |
| 测试与开发验证 | `tests\`、`scripts\` | 是 |
| 项目文档 | `docs\` | 是 |
| 本地数据库 | `data\*.db*` | 否 |
| 验证结果和日志 | `.artifacts\`、`.run-logs\`、`*.log` | 否 |
| 环境变量与虚拟环境 | `.env*`（除 `.env.example`）、`.venv\` | 否 |
| 内部评审材料 | `private\` | 否 |

## 上传前必须处理

- [ ] 立即在百炼控制台轮换历史文档中曾出现的 DashScope API Key。
- [x] 已加入 Apache License 2.0、第三方依赖声明和贡献指南；上传主体仍需确认其有权开源代码及素材。
- [ ] 使用 `.env.example` 配置本地 `.env`，确认 `.env` 中没有准备提交的真实凭据。
- [ ] 初始化 Git 后检查暂存清单，确认没有数据库、内部材料或生成产物。

若上传前继续修改代码，请重新运行下方验证命令。

## 验证命令

```powershell
python -m unittest discover -s tests -t .
python scripts\architecture_validation.py
python scripts\e2e_validation.py
python scripts\check_design_compliance.py
```

## 首次上传命令

```powershell
git init
git add .
git status --short
git diff --cached --check
git commit -m "Initial DriveMate V8 release"
git branch -M main
git remote add origin <your-repository-url>
git push -u origin main
```

执行 `git add .` 后，`git status --short` 中不应出现 `.env`、`private\`、
`data\*.db*`、`.artifacts\`、`.run-logs\` 或任何真实凭据。
