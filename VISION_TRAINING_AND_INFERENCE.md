# v31 视觉训练与推理

默认运行 `artifacts/submission/capture-v31/agent.py`。请按 [docs/QUICKSTART.md](docs/QUICKSTART.md) 在 ZqhjGame 仓库根目录执行安装、校验、训练和推理命令。

当前视觉方法为轮廓候选与 64×64 真车/诱饵/背景三类 CNN，沿用 appearance-v3 权重。当前源码精确对应 v31 的 17 个导出模块；未启用 Nano、旧 YOLO 检测网络或 YOPO 学习评分头。局部 CNN 训练读取已审核图片，完全离线；数据路径迁移步骤见 [资产清单](docs/ARTIFACT_HANDOFF.md#训练数据路径迁移)。

v31 的 seed101 完整 600 仿真秒单次成绩为 28.33 分、4 报告、RMSE 6.5411588239 米、0 惩罚、0/3 捕获，`passed=false`。结果见 [包内评分](artifacts/submission/capture-v31/evaluation.json)，不需要下载原回合录图。重训或重新运行不保证相同分数；当前尚未实现持续双机捕获，也不是视觉到轨迹端到端训练。

历史发布 v26 与 v22 基线、appearance-v3 训练记录和图片依赖继续保留。源码分工与问题见 [HANDOFF](docs/HANDOFF.md) 和 [KNOWN_ISSUES](docs/KNOWN_ISSUES.md)。
