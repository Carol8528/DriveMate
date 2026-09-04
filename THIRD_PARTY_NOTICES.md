# 第三方依赖声明

本项目运行依赖分别记录于 `requirements.txt` 与 `frontend/package.json`：

| 依赖 | 用途 | 许可证 | 项目地址 |
|---|---|---|---|
| Requests | 本地 REST、座舱模拟器及可选 CRM/百炼接口访问 | Apache License 2.0 | https://github.com/psf/requests |
| React / React DOM | Web 界面 | MIT | https://github.com/facebook/react |
| Vite | 前端构建 | MIT | https://github.com/vitejs/vite |

安装时还会解析上述包的间接依赖；其版本与许可证以实际安装环境生成的清单为准。发布构建前建议执行 `python -m pip freeze` 固化版本，并复核每项依赖随附的许可证文本。

仓库内图片和设计资产仅用于本参赛项目演示，不自动授予项目外单独再分发权利；贡献者应确保新增素材具有合法来源。
