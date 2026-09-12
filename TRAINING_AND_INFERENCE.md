# 当前训练与推理入口

当前推荐运行版本为 `artifacts/submission/capture-v26/agent.py`。seed101 的完整 600 秒请求回合取得 18.67 分、4 次报告、RMSE 9.67 米、0 惩罚、0/3 清除；尚未完成连续 20 秒捕获或多 seed 稳定性验证。完整安装、数据路径迁移、外观模型训练、导出和正式推理命令统一维护在 [docs/QUICKSTART.md](docs/QUICKSTART.md)。

当前模型为 appearance-v3 局部 CNN，当前规划器为解析固定翼运动基元规划器。v26 改进已确认任务的世界视线云台控制，没有重新训练，也未改变搜索、VERIFY、识别和报告门限。`learning/guidance.py` 等研究代码仍在源码中，但当前得分包没有使用 YOPO 学习评分头。当前模型的审核训练数据与图片依赖保留，旧实验移入本机归档。

score-v22 的 9.06 分完整回合基线保持冻结，供回归使用。要研究端到端 YOPO，需要重新组织合法数据、训练与验证，不能把当前得分当作该方法的成绩。协同控制与复测命令见 [双机接应说明](docs/COOPERATIVE_CAPTURE.md)，交接边界见 [交接总览](docs/HANDOFF.md)。
