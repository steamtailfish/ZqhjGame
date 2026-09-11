# score-v22 视觉训练与推理

请使用 [docs/QUICKSTART.md](docs/QUICKSTART.md) 中从 ZqhjGame 仓库根目录执行的命令。

当前路线为轮廓候选与 64×64 局部三类 CNN，而非旧 YOLO 视觉包。权重、审核数据、依赖图片和最新正式回合通过 Git LFS 随仓库提供，先执行 `git lfs pull`，再核验 [资产清单](docs/ARTIFACT_HANDOFF.md)。

当前成绩 9.06 分，2 次报告，0/3 清除；未实现双机持续捕获，也不是视觉到轨迹端到端训练。源码入口与问题见 [HANDOFF](docs/HANDOFF.md) 和 [KNOWN_ISSUES](docs/KNOWN_ISSUES.md)。
