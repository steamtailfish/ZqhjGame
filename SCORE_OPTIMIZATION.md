# 比赛得分优化、运行与复现

2026-09-11最新“先取得非零分”的构建、测试与命令见 [FIRST_SCORE.md](FIRST_SCORE.md)。下方保留score-v12阶段记录。

用户当前优先级是正式比赛得分。实验包为 `artifacts/submission/score-v12/`，采用独立异步视觉、双类检测、协同搜索和解析轨迹规划。此版本不调用YOPO分数头；先前学习产物保留，不把模块化方案称为端到端。

## 什么才算得分

赛题二至少2架有效无人机同时跟踪**同一辆真实目标**，累计20秒后判定清除。中断≤2秒保留并在恢复时回补；中断>2秒清零。不同飞机分别看不同目标、跟踪诱饵、仅产生检测框或进入自定义OBSERVE状态，都不能代替这个判定。组合可以改变，但同一时刻须满足K=2。无需武器指令。

目标清除占50%，三辆真目标每清除一辆贡献约16.67基础分；坐标上报精度占30%，未上报目标记0，误差基准120米；全部清除的完成速度占20%，240秒内满分、240–420秒衰减、420秒后该项为0。安全惩罚另外扣除。只清除目标而不上报，无法拿满分。

依据：`docs/manual/MANUAL_EXTRACT.md` B0084/B0140/T004；官方 `competition/sdk/_vendored/coop_eval.py` 的 `profile_multi_uav_coop_decoy`、`observe`、`_dimension`；`competition/sdk/core/runner.py` 的 `_observe_scoring`。裁判读取引擎实际跟踪关系并匹配目标，检测网络输出不是评分输入。官方文件未改动。

## 诊断与修改

- 轻负载通信对照确认41字节编码正常。同步视觉版本队友状态经常缺失；改成每机一个有界后台推理任务，保留原照片接收时刻和位姿，过期结果丢弃。120秒实测中两名队友可用率约96%，这不等于K=2。
- 协同搜索通过合法广播维持队形；远端候选不再被自身无关检测框覆盖。通信可附带估计地面高度和视觉身份，编码后45字符，仍小于50字节。
- 180秒回合的36个选中框裁剪已人工核对，主要是树木、石块和阴影。它们作为36张训练负样本加入原30张训练正样本；验证仍为原34张受控正样本。没有把完整照片自动标为空，也没有用预测伪造真值。
- 新模型完成50epoch微调。36个审核背景位置在完整图推理中的误检框从59降到0，阈值0.45。它们属于训练数据，**不能作为泛化结果**。原同布景验证集mAP50约0.994，仍不代表实战准确率。
- 像素伺服改成原接收姿态下图像射线对应的固定世界方向；同一照片不重复累加偏差，机头转动时补偿相对pan。采集时刻尚未校准，这不是绝对定位精度保证。
- 局部平面在短暂云台转动期间限时复用，受时间、距离、散布和工程误差预算约束。明确诱饵会清除候选缓存。

## 实测结果

| 实验 | 时长 | 官方分数 | 清除 | 惩罚 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| visual-v9 / seed88 | 600秒 | 0 | 0/3 | 4 | 未形成真实K=2 |
| async-v10 / seed89 | 120秒 | 0 | 0/3 | 0 | 通信改善，仍无任务得分 |
| score-v11 / seed90 | 180秒 | 0 | 0/3 | 0 | 共同OBSERVE意图最长约6.95秒；真实coop_ticks全0 |
| score-v12 / seed90 | 600秒 | 0 | 0/3 | 0 | 三机全程SEARCH，未建立地理轨迹或真实K=2 |

最新完整回合实际结束于599.983秒，墙钟1144.20秒。三机各1139次视觉处理，异常和异步过期丢弃均为0；满足搜索候选门限的帧只有3/2/9，均未建立地理轨迹。背景误检虽减少，真车捕获仍未解决，不能将score-v12称为高分版本。

外部判定补录覆盖约416.53秒、2035个采样帧。三机实际有效真车锁定均为0；其余为未锁定或诱饵。粗略几何视锥分析中，领机没有真车进入视锥，两架跟机仅在少量帧可能包含真车；该近似忽略遮挡和精确相机合同。实测支持优先修复搜索覆盖与真车捕获，而非只延长OBSERVE计时。不得根据这局真值坐标硬编码路线。

证据：`artifacts/vision/runs/score600-seed90/official/coop_decoy_1789045393.evaluation.json`、`artifacts/checks/score600-analysis/summary.json`、`judge-detail.json`与`judge-views.png`。600秒回放在同目录`score-replay.html`；无得分结果保留，不覆盖历史运行。

## 推理命令

以下PowerShell命令从发行包根目录执行。每次输出用新目录。

```powershell
Set-Location D:\catkin_ws\hf2026-sim-windows

# 当前实验包，完整600秒，模型资产已包含
.\ZqhjGame\vision.cmd run --ue-direct --duration 600 --seed 91 --submission ZqhjGame/artifacts/submission/score-v12/agent.py --enable-reports --max-photos 500 --output ZqhjGame/artifacts/vision/runs/score-v12-retest91

# 私有模型、独立导入、回调禁止文件访问检查
.\ZqhjGame\.venv-learning\Scripts\python.exe -B -I ZqhjGame/tools/check_visual_package.py ZqhjGame/artifacts/submission/score-v12/agent.py --output ZqhjGame/artifacts/checks/score-v12-retest-isolation.json

# 回合结束后分析
.\ZqhjGame\.venv-learning\Scripts\python.exe -B ZqhjGame/tools/analyze_score_run.py ZqhjGame/artifacts/vision/runs/score-v12-retest91 --output ZqhjGame/artifacts/checks/score-v12-retest91.json
```

包内CPU/1024/检测阈值0.45固定；搜索候选另要求非诱饵且置信度≥0.55。`--weights/--controller/--confidence`不会覆盖提交包。上报默认关闭，实验命令开启后仍需通过现有身份、时空和负责人门限。不要用缺少Torch的发行包Python加载视觉Agent。

## 训练与导出命令

```powershell
# 用已人工核对的记录重建数据集
.\ZqhjGame\vision.cmd dataset --task identity --reviewed ZqhjGame/artifacts/vision/datasets/background-review-v1/accepted.jsonl --val-episode true-height200 --val-episode decoy-height200 --output ZqhjGame/artifacts/vision/datasets/background-rebuild

# 复现此次50epoch微调
.\ZqhjGame\vision.cmd train --data ZqhjGame/artifacts/vision/datasets/background-rebuild/data.yaml --weights ZqhjGame/artifacts/vision/models/identity-refine-v2/fit/weights/best.pt --epochs 50 --batch 8 --size 256 --device cpu --freeze 0 --lr 0.0003 --output ZqhjGame/artifacts/vision/models/background-rebuild

# 导出协同搜索包，隐含异步视觉
.\ZqhjGame\vision.cmd export --weights ZqhjGame/artifacts/vision/models/background-rebuild/fit/weights/best.pt --geometry estimated --team-search --output ZqhjGame/artifacts/submission/score-rebuild
```

YOPO式结构化轨迹训练见 `TRAINING_AND_INFERENCE.md`；视觉安装、原始训练和采集见 `VISION_TRAINING_AND_INFERENCE.md`。后续数据须扩展布景、尺度、视角与遮挡。

## 可视化与判定诊断

`artifacts/checks/team180-analysis/score-replay.html`展示自身航迹、同照片哈希对应检测框与局部放大；图片时间单独标出，非精确同步视频。`selected.png`为36处人工审核图册。

`tools/record_judge_trace.py`是用户要求可视化排障后添加的**独立外部只读观察器**。它不导入Agent、不发布命令、不改变评分，不将裁判信息返回在线策略。仅在回合结束后分析其记录。不得将该工具、裁判真值或目标路线加入提交包或策略特征。本次补录为部分时间段，不代表全回合遥测。
