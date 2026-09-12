# ZqhjGame 工作约定

- 当前唯一保留的提交基线为 score-v22：seed101，600 秒请求 / 599.917 秒记录，9.06 分、2 报告、0/3 清除、0 惩罚、RMSE 11.27 米。三个目标 coop_ticks 均为 0，不得把精度分称为双机捕获。
- 2026-09-12 新增协同状态机。capture-v23/v24 完整回合均为 0 分、0 报告、0 清除，未发起任务；当前 capture-v25 保持 VERIFY 搜索航迹并新增最多 1.5 秒的云台稳定窗口，见 docs/COOPERATIVE_CAPTURE.md。不得把 v22 分数或本地联合观察计时当作新候选的捕获成绩；保留 v22 冻结包直到新候选充分验证。
- capture-v25 已实测 300 秒请求 / 299.9667 秒记录，seed101，9.27 分、2 报告、RMSE 8.7472 米、0 惩罚、0 清除。两次召集与接应确认成功，均因视觉恢复超时释放；官方 coop_ticks=0，未做完整 600 秒/多 seed 验证，不把短回合与 v22 直接比较。
- 用户要求只保留最近版本并上传全部当前资产。当前 artifacts 保留 v22 得分基线、最新协同候选、appearance-v3 及依赖训练图片，以及验证记录和报告。旧资产移入 .local-archive/pre-v22-20260911；本轮失败中间包移入 .local-archive/capture-development，原始失败评分和诊断摘要保留。归档不加入 Git，不重写既有 Git 历史。
- artifacts 使用 Git LFS，-text 保持冻结代码/权重/原始结果字节一致；本机环境、缓存和 accepted-local.jsonl 不提交。训练图片所在目录可能含旧名称，它们是当前 v22 的数据依赖，不能按名称删除。
- 项目与 Git 根目录为 ZqhjGame；官方 SIM_ROOT 默认为父目录。自研写入仅在本项目内，官方 SDK、引擎、原场景和评分只读。保留未提交修改，不执行 reset/clean 或全局进程清理。
- 在线 Agent 只用 obs.self、obs.comm_inbox、obs.briefing 与实例状态。队友状态经合法通信；禁止读取 Redis、隐藏路线、裁判真值、其他 Agent 对象和磁盘截图作为在线输入。
- 赛题二：3 机，K=2 同目标连续20秒，短中断容忍2秒；通信50字节/4Hz，高度500米、速度15–40米/秒、FOV5–50度。正式成绩以原始 evaluation 为准，mAP、OBSERVE、回放和合成检查不能替代。
- 当前方法是局部 CNN 视觉分类、图像运动几何定位及解析规划；YOPO 学习评分头未参与当前得分。研究源码可保留，不自动部署未经验证的权重。
- 开发修改 src，导出至新目录后运行新包；不修改 score-v22 的 agent.py、vision.pt 和 baseline_evaluation.json。导出器默认控制函数来源为冻结 score-v22/agent.py，解析分支不启用其中历史学习权重。
- 入口与当前命令见 docs/QUICKSTART.md；当前状态见 STATUS.md，问题见 docs/KNOWN_ISSUES.md，资产清单见 docs/ARTIFACT_HANDOFF.md。接口依据见 docs/SDK_CONTRACT.md、docs/ENVIRONMENT_AUDIT.md、docs/manual/MANUAL_EXTRACT.md。
- 外部裁判记录仅供赛后诊断，不反馈在线策略或身份训练标签。固定翼真实双机捕获与泛化尚未验证，后续先保留基线再单项优化。
