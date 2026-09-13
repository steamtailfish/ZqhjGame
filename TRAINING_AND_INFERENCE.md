# 当前训练与推理入口

当前发布与推荐运行入口为 `artifacts/submission/capture-v31/agent.py`。seed101 完整 600 仿真秒请求回合取得单次 28.33 分、4 报告、RMSE 6.5411588239 米、0 惩罚、0/3 捕获，`passed=false`。尚无连续 20 秒捕获或多 seed 稳定性结论。

安装、冻结包校验、训练图片迁移、局部 CNN 训练、导出和完整比赛命令统一维护在 [docs/QUICKSTART.md](docs/QUICKSTART.md)。直接推理无需训练集和旧比赛录图；历史得分可查看包内 [evaluation.json](artifacts/submission/capture-v31/evaluation.json)。

当前 `src/` 对应冻结 v31 的 17 个模块，使用 appearance-v3 局部 CNN、运动几何定位和解析固定翼规划。v31 新增近圈四秒圆弧终点及匹配曲率转率，没有重训，也没有启用 Nano 或 YOPO 学习评分头。局部外观训练直接读取审核图片，不启动 UE；引导学习研究代码仍保留，但未参与当前得分。

历史发布 v26 的 18.67 分与 v22 的 9.06 分保持原记录；v22 仍提供导出函数和训练依赖。重训模型或修改源码后必须独立评估，不能继承 v31 分数。方法见 [双机接应说明](docs/COOPERATIVE_CAPTURE.md)，交接范围见 [资产清单](docs/ARTIFACT_HANDOFF.md)。
