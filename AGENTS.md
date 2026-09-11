# ZqhjGame 工作约定

- 当前唯一保留的提交基线为 score-v22：seed101，600 秒请求 / 599.917 秒记录，9.06 分、2 报告、0/3 清除、0 惩罚、RMSE 11.27 米。三个目标 coop_ticks 均为 0，不得把精度分称为双机捕获。
- 用户要求只保留最近版本并上传全部当前资产。当前 artifacts 仅保留 v22、appearance-v3、其依赖训练图片、正式回合、验证记录和报告。旧资产已可恢复地移入 .local-archive/pre-v22-20260911，不加入 Git；不重写既有 Git 历史。
- artifacts 使用 Git LFS，-text 保持冻结代码/权重/原始结果字节一致；本机环境、缓存和 accepted-local.jsonl 不提交。训练图片所在目录可能含旧名称，它们是当前 v22 的数据依赖，不能按名称删除。
- 项目与 Git 根目录为 ZqhjGame；官方 SIM_ROOT 默认为父目录。自研写入仅在本项目内，官方 SDK、引擎、原场景和评分只读。保留未提交修改，不执行 reset/clean 或全局进程清理。
- 在线 Agent 只用 obs.self、obs.comm_inbox、obs.briefing 与实例状态。队友状态经合法通信；禁止读取 Redis、隐藏路线、裁判真值、其他 Agent 对象和磁盘截图作为在线输入。
- 赛题二：3 机，K=2 同目标连续20秒，短中断容忍2秒；通信50字节/4Hz，高度500米、速度15–40米/秒、FOV5–50度。正式成绩以原始 evaluation 为准，mAP、OBSERVE、回放和合成检查不能替代。
- 当前方法是局部 CNN 视觉分类、图像运动几何定位及解析规划；YOPO 学习评分头未参与当前得分。研究源码可保留，不自动部署未经验证的权重。
- 开发修改 src，导出至新目录后运行新包；不修改 score-v22 的 agent.py、vision.pt 和 baseline_evaluation.json。导出器默认控制函数来源为冻结 score-v22/agent.py，解析分支不启用其中历史学习权重。
- 入口与当前命令见 docs/QUICKSTART.md；当前状态见 STATUS.md，问题见 docs/KNOWN_ISSUES.md，资产清单见 docs/ARTIFACT_HANDOFF.md。接口依据见 docs/SDK_CONTRACT.md、docs/ENVIRONMENT_AUDIT.md、docs/manual/MANUAL_EXTRACT.md。
- 外部裁判记录仅供赛后诊断，不反馈在线策略或身份训练标签。固定翼真实双机捕获与泛化尚未验证，后续先保留基线再单项优化。
