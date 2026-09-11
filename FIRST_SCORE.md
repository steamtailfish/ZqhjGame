# 训练、推理与首个正式分数

当前验收：先取得非零正式分数，再优化高分。只以未修改正式场景的原始 evaluation JSON 为准。

## 当前版本与结果

已完成正式测试包 `artifacts/submission/score-v22`：seed101，请求600秒，官方记录结束于599.917秒；最终 **9.06分、2次报告、0清除、0惩罚**，报告定位RMSE为11.27米。分数来自坐标精度，三个目标coop_ticks均为0，尚未完成双机持续捕获。代码与权重在运行期间冻结；这是一次正式非零成绩，不代表稳定高分或独立泛化测试。

| 包 | 正式回合 | 分数 | 报告 | 清除 | 惩罚 |
| --- | --- | --- | --- | --- | --- |
| score-v13 | seed101，600秒 | 0 | 0 | 0 | 0 |
| score-v14 | seed102，600秒 | 0 | 0 | 0 | 0 |
| score-v15 | seed103，600秒 | 0 | 1 | 0 | 0 |
| score-v18 | seed101，600秒 | 0 | 0 | 0 | 0 |
| score-v19 | seed101，600秒 | 0 | 1 | 0 | 0 |
| score-v21 | seed101，600秒 | 0 | 0 | 0 | 0 |
| score-v22 | seed101，600秒 | **9.06** | **2** | **0** | **0** |

原始评分：`artifacts/vision/runs/score600-v22-seed101/official/coop_decoy_1789108334.evaluation.json`。提交包中的`baseline_evaluation.json`为其原样副本；代码/权重与正式运行哈希绑定。运行途中曾显示9.47分，最终累计精度更新为9.06分，以最终JSON为准。

v15/v19的错误报告RMSE分别为1577.36/1371.89米。v16/v17/v20只做过回放等检查，没有正式成绩。

捕获确实要求两架无人机对同一真实目标满足引擎有效跟踪条件并持续20秒，短中断容忍2秒。坐标精度另有得分项，可在尚未清除目标时得分；必须分别报告分数、报告数和清除数，不能把精度得分称为双机捕获。

## 当前实现

采用轮廓候选、64×64局部外观网络、本机图像运动定位、坐标报告和广播协同。当前部署是模块化感知和解析规划，未调用YOPO评分头，也不是端到端视觉规划。原引导学习代码及历史说明保留在TRAINING_AND_INFERENCE.md和docs/YOPO_SCOPE.md。

- 三机用公开任务边界及合法广播分配搜索条带，间隔280米，搜索速度35米/秒，FOV50度。
- appearance-v3在人工审核的35个真车、17个诱饵、709个背景局部样本上训练2400步。车辆标签来自受控采集；正式照片只增加人工确认的背景。34个受控验证样本全对，不代表正式地图泛化精度。
- 云台转动后的目标关联使用图像单应变换，必要时用本机相机姿态估计；单次pan/tilt变化限制为6/3度。已验证目标可保留8秒用于稳定云台，报告仍需要新鲜证据。
- v22报告只走严格的短像素轨迹路径：至少4帧连续像素跟踪，其中最近3帧真车置信度≥0.95、类别分差≥0.9；至少2次相邻且一致的地理估计，工程预算≤110米，照片年龄≤0.6秒，云台俯角至少70度；按同一图像平面换算的相对背景速度须在3.5–18米/秒，并通过连续运动检查。
- 报告不等待导航轨迹确认，与其他报告共用1Hz限制。原地理轨迹报告路径在v22中关闭，地理轨迹仍供协同控制使用。运动门限可能漏掉慢车，这是当前先分辨背景误报的工程取舍。
- 提交包默认开启有门限的报告，SDK直接加载EntryAgent时也生效。

在线只使用本机公开照片、位姿、briefing和合法通信。裁判记录只用于回合结束后的外部诊断，不进入Agent、训练标签或搜索路线。照片时间仍为接收时刻，未验证为拍摄时刻；定位预算不是已标定的概率保证。

## 训练命令

在PowerShell从发行包根目录执行。输出目录必须用新名称；本机已配置项目专用`.venv-learning`，新机器环境准备见VISION_TRAINING_AND_INFERENCE.md。

```powershell
Set-Location D:\catkin_ws\hf2026-sim-windows
.\ZqhjGame\.venv-learning\Scripts\python.exe -B ZqhjGame/tools/train_vehicle_appearance.py --reviewed ZqhjGame/artifacts/vision/datasets/appearance-data-v3/accepted.jsonl --output ZqhjGame/artifacts/vision/models/appearance-rebuild --steps 2400
.\ZqhjGame\vision.cmd export --weights ZqhjGame/artifacts/vision/models/appearance-rebuild/appearance.pt --patch-appearance --geometry estimated --distributed-search --reports-default-on --output ZqhjGame/artifacts/submission/first-score-rebuild
```

训练读取已有人工审核图像和标签，不启动比赛。重新训练的权重需要重新验证，不继承冻结包的成绩。已有权重可直接导出，不必重新训练：

```powershell
.\ZqhjGame\vision.cmd export --weights ZqhjGame/artifacts/vision/models/appearance-v3/appearance.pt --patch-appearance --geometry estimated --distributed-search --reports-default-on --output ZqhjGame/artifacts/submission/first-score-export
```

当前权重SHA256：`819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf`。包内vision.pt为局部分类网络state_dict，必须带`--patch-appearance`。原照片仍是1024×768，64是分类裁剪尺寸。

## 推理命令

直接使用已冻结的v22，无需重新训练。每次重跑修改输出目录；不要同时启动两个UE/Redis比赛。

```powershell
Set-Location D:\catkin_ws\hf2026-sim-windows
.\ZqhjGame\.venv-learning\Scripts\python.exe -B -I ZqhjGame/tools/check_visual_package.py ZqhjGame/artifacts/submission/score-v22/agent.py --output ZqhjGame/artifacts/checks/score-v22-retest-isolated.json
.\ZqhjGame\vision.cmd run --ue-direct --duration 600 --seed 104 --submission ZqhjGame/artifacts/submission/score-v22/agent.py --enable-reports --max-photos 500 --output ZqhjGame/artifacts/vision/runs/score-v22-retest104
.\ZqhjGame\.venv-learning\Scripts\python.exe -B ZqhjGame/tools/analyze_score_run.py ZqhjGame/artifacts/vision/runs/score-v22-retest104 --output ZqhjGame/artifacts/checks/score-v22-retest104.json
```

分析命令必须等待回合完成。正式原始结果位于运行目录`official/*.evaluation.json`。要提交SDK，请将同一导出目录内的agent.py和vision.pt保留在一起；每架无人机初始化自己的私有模型，回调不读取模型文件。

## 验证证据

- `artifacts/checks/score-v22-isolated.json`：三份私有模型、隔离导入、回调文件I/O禁止条件下的推理检查通过。
- `learning/test_score_search.py`：10项报告、关联、运动新鲜度、云台步幅和搜索分工检查；`learning/test_vision.py`：17项检查。它们不是比赛分数。
- `artifacts/checks/true-moving-replay-v22-u2.json`：受控移动真车照片回放12次报告；`decoy-moving-replay-v22-u2.json`：诱饵回放0报告。广播为合成输入，命令不影响后续照片，非闭环成绩。
- `docs/FIRST_SCORE_DIAGNOSIS.md`：v18/v19已经出现准确定位但未上报的失败链路，以及新门限依据。
- 历史旋转微调、尺寸增强及旧命令见`docs/FIRST_SCORE_HISTORY_V19.md`、SCORE_OPTIMIZATION.md。未把历史mAP当作正式任务成绩。
