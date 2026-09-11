# ZqhjGame

最新目标与命令：[先取得非零正式分数](FIRST_SCORE.md)。当前新增旋转训练、扩大搜索覆盖和视觉上报门限验证；正式成绩以该页记录为准。

当前得分优化实验、评分条件及新训练/推理命令：[SCORE_OPTIMIZATION.md](SCORE_OPTIMIZATION.md)。score-v12加入异步视觉、背景负样本训练和协同搜索；尚无高分验收。下方保留既有学习路线记录。

最新完整视觉/控制包及命令：[VISION_TRAINING_AND_INFERENCE.md](VISION_TRAINING_AND_INFERENCE.md)。已完成双类视觉训练、三机自身RGB推理、实验性地理估计、导航适配和单模块+权重包。最新实测仍0分、0/3；真实K=2和跨场景精度未通过。证据见[本轮验收](docs/VISUAL_CLOSED_LOOP.md)。

**训练与推理主入口：[TRAINING_AND_INFERENCE.md](TRAINING_AND_INFERENCE.md)**。v0.3已接通真实公开观测采集、51维比赛边界/机体系适配、引导学习、续训、单文件权重导出与标准库在线推理。正式视觉识别/定位和真实K=2验收仍未完成。

红枫2026赛题二自研代码。当前是参考Gou围捕引导策略和YOPO轨迹评价思想实现的解析控制基线，入口已能返回飞行、云台和广播命令。

`learning/guidance.py`实现轨迹成本反传和分数头训练；独立学习环境中的模型可经`learn.cmd export`导出，`run.cmd --submission`加载。主命令文档包含本轮已验证的权重路径。早期机制验证见[引导学习历史说明](docs/GUIDANCE_LEARNING.md)。

| 模块 | 职责 |
| --- | --- |
| `src/zqhj_entry.py` | 官方Agent入口和在线串联 |
| `src/zqhj_state.py` | 合法仿真时间、检测归一化、含噪短轨迹 |
| `src/zqhj_comm.py` | 41字节广播、2Hz限频、去重和TTL |
| `src/zqhj_cooperation.py` | 双机候选接应、第三机搜索、上报证据门限 |
| `src/zqhj_planner.py` | APF引导、固定翼候选轨迹、约束检查 |
| `src/zqhj_localization.py` | 已有严格条件的图像地面投影组件 |
| `src/zqhj_vision.py` | 内存 RGB 解码、单类车辆候选和限幅图像反馈 |
| `src/zqhj_photo_entry.py` | 三机私有视觉状态、重复帧/异常处理、屏蔽SDK后备检测 |

从官方环境根目录运行：

```powershell
.\ZqhjGame\run.cmd test
.\ZqhjGame\run.cmd dry-run --agent zqhj_entry:EntryAgent --redis-port 6395
.\ZqhjGame\run.cmd agent --agent zqhj_entry:EntryAgent --duration 8 --redis-port 6395
```

解析在线入口不需要新增Python依赖。可选学习模块使用独立PyTorch环境，见`requirements-learning.txt`。在线入口不读文件/Redis/路线/裁判真值。工程层的实验产物保存在`artifacts/`。

解析实现依据、算法边界、协议和运行说明见[论文与代码对应](docs/PAPER_GUIDED_IMPLEMENTATION.md)，验收结果见[STATUS](STATUS.md)。目前已用真实引擎公开观测训练并运行神经控制，未完成在线视觉识别或真实K=2验收，未核实的候选不会直接上报。
