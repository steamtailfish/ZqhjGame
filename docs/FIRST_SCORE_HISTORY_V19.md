# 先取得非零正式分数

2026-09-11，用户将当前验收收敛为先取得非零分，再逐步优化。以未修改的正式场景evaluation为准，不以合成分数、mAP或自定义OBSERVE状态替代。

## 最新进展（v19 待正式验证）

v15 已结束：0分、1报告、0清除、0惩罚，报告 RMSE 1577.36米。v18 已完成600秒：0分、0报告、0清除、0惩罚。当前修复包为 `artifacts/submission/score-v19`，已通过隔离提交检查和8项报告/关联检查；受控移动照片开环回放产生13次上报，正式seed101对照回合运行中，尚无最终分数。

v16 增加相对背景的连续运动证据，过滤静止背景报告；v17 将该检查用于地理协同候选。v19 修复云台转动后的跨帧目标关联：用图像单应变换预测新像素位置，缺少图像变换时用本机相机姿态估计；单次云台pan/tilt变化分别限制为6/3度。已验证目标的云台跟踪可保留8秒，报告和地理候选仍必须有新鲜运动证据。地面深度拟合仍要求姿态稳定。

v18 起导出增加 `--reports-default-on`，确保正式 SDK 直接加载 EntryAgent 时也开启有门限的上报。下面历史 v15 命令保留作为运行记录；最新命令请用本节：

```powershell
Set-Location D:\catkin_ws\hf2026-sim-windows
.\ZqhjGame\.venv-learning\Scripts\python.exe -B ZqhjGame/tools/train_vehicle_appearance.py --reviewed ZqhjGame/artifacts/vision/datasets/appearance-data-v3/accepted.jsonl --output ZqhjGame/artifacts/vision/models/appearance-rebuild --steps 2400
.\ZqhjGame\vision.cmd export --weights ZqhjGame/artifacts/vision/models/appearance-rebuild/appearance.pt --patch-appearance --geometry estimated --distributed-search --reports-default-on --output ZqhjGame/artifacts/submission/first-score-rebuild
.\ZqhjGame\.venv-learning\Scripts\python.exe -B -I ZqhjGame/tools/check_visual_package.py ZqhjGame/artifacts/submission/score-v19/agent.py --output ZqhjGame/artifacts/checks/score-v19-retest-isolated.json
.\ZqhjGame\vision.cmd run --ue-direct --duration 600 --seed 104 --submission ZqhjGame/artifacts/submission/score-v19/agent.py --enable-reports --max-photos 500 --output ZqhjGame/artifacts/vision/runs/score-v19-retest104
.\ZqhjGame\.venv-learning\Scripts\python.exe -B ZqhjGame/tools/analyze_score_run.py ZqhjGame/artifacts/vision/runs/score-v19-retest104 --output ZqhjGame/artifacts/checks/score-v19-retest104.json
```

每次重跑使用新的输出目录。训练后的新权重需重新验证，不继承冻结包成绩。正式推理可直接使用已导出的v19，无需重新训练；把agent.py和vision.pt保留在一起。不要并行启动比赛。

捕获规则确实要求两架无人机持续有效跟踪同一真实目标20秒，短中断容忍2秒；坐标精度另有得分项。若首先通过精度获得分数，必须单独列出清除数，不能声称已完成双机捕获。

## v13–v15 修改记录

- 当前正式测试包为`artifacts/submission/score-v15`，采用轮廓候选→64×64局部外观网络→本机运动平面定位→独立坐标上报和广播协同。它不调用YOPO评分头，也不是端到端视觉规划；当前先以正式非零分验收。
- `appearance-v3`在35个真车局部样本、17个诱饵样本、709个已审核背景局部样本上训练2400步，CPU用时15.14秒。34个受控验证样本分类正确，但仍不代表跨场景身份准确率。新增车辆只来自受控场景中人工确认的可见车框；正式照片仅添加19张人工确认背景，未以裁判坐标或ID制作标签。
- 六张正式照片对照中的五个真车区域被正确识别，置信度约0.81–1.00；高置信候选总数从appearance-v2的27个降到v3的10个，其中仍有未核实候选，不能把10个都算真车。单张照片处理约45毫秒。密集受控移动照片开环回放产生17次上报，非正式分数。
- `ScoreSearchAgent`用公开任务边界和广播发现的队友分配搜索条带，间隔280米；搜索速度35米/秒、FOV50度。确认地理候选后仍使用既有协同会合，避免三机始终重复扫描领机附近。
- 视觉模型在原审核数据上执行80epoch旋转微调，`degrees=180`、`flipud=0.5`。原训练/验证布景相似的局限仍存在，旋转验证不是跨场景精度。
- 原模型在34张验证裁剪的90°/270°视图上匹配数均为0；新模型分别34/34和32/34。类别判断正确数分别31/34和23/34，不把检出率当身份准确率。
- 36处审核背景的完整图回归仍为0误检，但它们已用于训练，不能作为未见场景结果。
- 局部平面稳定性用机头航向加相对云台pan的实际光轴方位变化，避免两者相互抵消时仍被误判为相机大幅转动。
- score-v13保留0.9/0.6身份门限，作为已冻结的第一轮正式测试。旋转验证随后发现该门限不匹配新模型输出，准备score-v14：身份置信度0.65、类别分差0.35、连续4个地理身份样本、定位工程预算≤110米。其余负责人、照片哈希、轨迹关联、新鲜度和1Hz限制仍保留。该工程预算不是经过标定的概率保证。
- 在136个旋转标签中，新门限保留25个正确真车识别、没有已匹配诱饵误判为真车；这是有限验证样本上的门限选择，未证明比赛误报率为0。

## 正式测试

| 包 | 正式运行 | 状态 |
| --- | --- | --- |
| score-v13 | score600-seed101，600秒 | 已完成599.950秒：0分、0清除、0报告、0惩罚 |
| score-v14 | score600-seed102，600秒 | 已完成：0分、0清除、0报告、0惩罚 |
| score-v15 | score600-seed103，600秒 | 已完成：0分、1报告、0清除、0惩罚，RMSE 1577.36米 |

v13三机分别产生119/60/39个视觉候选帧和28/7/6个地理估计帧，但0.9/0.6身份门限仅通过1/0/0帧。外部约595秒诊断记录中，两机分别有23、89个实际真车有效锁定采样，仍没有同目标双机采样；官方三个目标coop_ticks均为0。36张选中候选的完整裁剪人工复核仍为石块/树木，说明仅降低身份阈值不足以解决泛化。

identity-small-v5已训练80epoch：只把原受控训练车辆缩到0.45/0.65倍，并增加上述36张人工确认的背景裁剪；162张训练、34张原验证，未把裁判坐标、目标编号或诊断真车投影转成训练标签。正式照片的六个可见车辆区域保留作漏检诊断。v4在1024/1536/2048分辨率上分别仅在其中1/1/1处给出≥0.25的框，v5分别0/1/0处；未改善正式照片漏检，未部署。

下一版源码已将精度上报与双机分工解耦：本机通过4次身份、当前框、地理一致性与时效检查后，即使另两机被分配观察其他候选，也可以报告本机坐标。仍保留1Hz限制，未修改K=2/20秒捕获规则。该修改不在v14冻结包中。新增诊断记录身份连续次数和本机报告轨迹，便于区分门限拒绝与实际漏检。

感知备选实验：`zqhj_patch_vision.py`实现多亮度轮廓候选和64像素局部外观分类；`appearance-v1`仅用原审核车框和背景训练，34张受控验证全对，但正式照片只识别出部分车辆且仍有多处误检，尚未部署。继续补采多朝向受控车辆。`true-moving-v1`/`decoy-moving-v1`虽然配置了路径但未激活，视为静止摆放；v2通过采集专用set_trajectory命令激活，只作用于fixture副本，原正式场景不变。

## 复现训练

在PowerShell中从发行包根目录执行。输出目录须为新目录。

```powershell
Set-Location D:\catkin_ws\hf2026-sim-windows
.\ZqhjGame\.venv-learning\Scripts\python.exe -B ZqhjGame/tools/train_vehicle_appearance.py --reviewed ZqhjGame/artifacts/vision/datasets/appearance-data-v3/accepted.jsonl --output ZqhjGame/artifacts/vision/models/appearance-rebuild --steps 2400
.\ZqhjGame\vision.cmd export --weights ZqhjGame/artifacts/vision/models/appearance-rebuild/appearance.pt --patch-appearance --geometry estimated --distributed-search --output ZqhjGame/artifacts/submission/first-score-rebuild
```

上述训练只读取已有审核图像及标签；不启动比赛。当前v15使用`artifacts/vision/models/appearance-v3/appearance.pt`，SHA256为`819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf`。`vision.pt`在此包内是局部分类网络的state_dict，不是Ultralytics模型；导出时必须带`--patch-appearance`。

历史YOLO旋转微调的复现命令如下，未作为当前推荐感知方案：

```powershell
.\ZqhjGame\vision.cmd train --data ZqhjGame/artifacts/vision/datasets/identity-background-v3/data.yaml --weights ZqhjGame/artifacts/vision/models/identity-background-v3/fit/weights/best.pt --epochs 80 --batch 8 --size 256 --device cpu --freeze 0 --lr 0.0003 --degrees 180 --flipud 0.5 --output ZqhjGame/artifacts/vision/models/rotation-rebuild
```

本次已训练权重：`artifacts/vision/models/identity-rotation-v4/fit/weights/best.pt`，SHA256为`35b558d0d1f5a87319c6f9a89861fb072d463c6525630701d28e076e2802dd0d`。

## 推理与检查

```powershell
.\ZqhjGame\vision.cmd run --ue-direct --duration 600 --seed 104 --submission ZqhjGame/artifacts/submission/score-v15/agent.py --enable-reports --max-photos 500 --output ZqhjGame/artifacts/vision/runs/score-v15-retest104
.\ZqhjGame\.venv-learning\Scripts\python.exe -B -I ZqhjGame/tools/check_visual_package.py ZqhjGame/artifacts/submission/score-v15/agent.py --output ZqhjGame/artifacts/checks/score-v15-retest-isolated.json
.\ZqhjGame\.venv-learning\Scripts\python.exe -B ZqhjGame/tools/analyze_score_run.py ZqhjGame/artifacts/vision/runs/score-v15-retest104 --output ZqhjGame/artifacts/checks/score-v15-retest104.json
```

模型在初始化时私有加载，回调只读本机照片。原始照片仍是1024×768；64是分类裁剪尺寸。包的搜索候选阈值为0.55，真车上报身份门限为0.65/类别分差0.35，需连续4个有效地理身份样本、工程定位预算≤110米，并通过照片哈希、新鲜度、轨迹关联和1Hz检查。`--enable-reports`仅开启这些有条件的报告，默认关闭。不要同时启动两场UE/Redis比赛。环境重建与接口约束见VISION_TRAINING_AND_INFERENCE.md，历史0分记录见SCORE_OPTIMIZATION.md。

## 验证证据

`artifacts/checks/rotation-regression-v4.json`、`rotation-identities-v4.json`、`rotation-background-v4.json`记录旋转与背景检查。`learning/test_score_search.py`确认满足视觉门限时会产生报告，弱身份、过期观测或过大误差预算会拒绝报告；这是合成输入检查，不是正式比赛成绩。

`fixture-reports-v14.json`记录受控真实照片开环回放中23秒发出一次上报，队友广播为合成输入，未运行裁判。`fixture-localization-v13.json`中的64个已审核像素定位均有估计，四个受控回合误差中位数约3.0–4.8米，采用最近静态参考的乐观匹配，不能冒充正式移动目标精度。v13正式原始evaluation及外部诊断分别位于`artifacts/vision/runs/score600-seed101/official/`与`artifacts/checks/score101-judge-analysis.json`。
