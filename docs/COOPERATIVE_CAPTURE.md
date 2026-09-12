# 三机搜索与双机接应：capture-v25

2026-09-12。当前候选 capture-v25 实现“三机先搜索，可靠发现后两机跟踪，剩余一机继续搜索”。score-v22 的 9.06 分基线保持冻结。当前权重沿用 appearance-v3，没有重新训练，也没有启用 YOPO 学习评分头。

**当前实测：300 秒请求 / 299.9667 秒记录，seed101，9.27 分、2 次坐标报告、RMSE 8.7472 米、0 惩罚、0/3 清除。已发起两次接应任务，但没有形成有效双机跟踪，官方 `passed=false`。** 该成绩来自坐标精度，尚未完成 600 秒复测或多 seed 验证。

## 行为与规则

三架无人机按公开区域分工搜索。目标总数为 3 并不意味着每架飞机能预先知道一辆真实目标的位置；任务由公开照片产生，诱饵仍需排除。

| 状态 | 实际行为与退出条件 |
| --- | --- |
| SEARCH | 独立搜索；已有双机任务时第三架继续搜索 |
| VERIFY | 沿原搜索航迹积累视觉确认，最多 8 秒；未确认候选不改变飞行目标，也不召唤队友 |
| OFFER | 有运动验证、连续身份和一致地理定位后，发现机选择预计到达最快的空闲队友 |
| APPROACH | 队友确认任务后赶赴接应；发现机继续观察，接应机指向广播位置并独立寻找目标 |
| TRACK_PAIR | 两机各有新鲜、独立的图像证据，并匹配同一任务位置，才累计本地联合观察时间 |
| RECOVER | 短暂失去视觉后恢复；中断超过 2 秒重置本地累计时间 |
| RELEASE | 本地累计 25 秒或恢复/接应超时后释放，广播 2 秒，再回到搜索 |

正式规则要求两机对同一真实目标连续有效跟踪 20 秒，短中断容忍 2 秒。本地 25 秒包含控制余量，但**不能证明裁判捕获成功**：引擎还会判断有效检测和真实目标归属。日志始终标记 `judge_confirmed=false`。本地完成后的区域冷却也不等于已清除目标。

## 身份与通信

- 召集需要连续至少 3 帧满足真车概率 ≥0.95、类别分差 ≥0.9，并通过运动验证与至少两次一致地理估计，定位预算 ≤110 米。持续观察的当前帧门限为概率 ≥0.9、分差 ≥0.8。相机接收年龄 ≤0.8 秒；尚未获得可信的实际拍摄时间戳。
- 接应机通过自身照片确认，绑定本机像素轨迹和任务编号；初次绑定距离门限 80 米，维持门限 160 米。仍可能因定位误差或相邻车辆发生错误关联。
- 任务编号由“发现机 UID + 本机递增序号”组成，不使用裁判隐藏目标 ID。广播包含发现机/接应机槽位、阶段、视觉有效标记、目标位置和速度。
- 新通信包为 49 个 ASCII 字节、每秒最多 2 次，符合 50 字节/4 Hz 限制；兼容原通信包的解析。
- 接应等待依据距离和航向估算，限制在 45–160 秒；8 秒未确认可改选另一架空闲机。单次任务最多 200 秒，所有有效视觉丢失 8 秒释放。

## 飞行与识别的限制

近目标时巡航参考速度设为 18 米/秒，期望盘旋半径约 320/360 米；接应途中参考速度为 32 米/秒，搜索为 35 米/秒。实际速度由固定翼运动基元与障碍约束共同选择，并非始终等于参考值。相机按位置引导接近，再交给像素伺服。

v25 在运动已验证但连续定位尚未确认时，最多保持当前云台角度 1.5 秒，让定位模块取得稳定的相邻照片；连续定位通过或时间到达即结束保持，同一像素轨迹不会反复续期。该窗口不改变飞行路线，也不降低识别或报告门限。

第三架保持搜索，但此实现同一时刻只保留一个共享双机任务；尚未实现第三架的多目标候选队列。ETA 不含完整绕障路线。地面估计、图像真假识别、两机关联和云台覆盖仍是实测风险。用于短暂 VERIFY 的近似地面高度不作为坐标上报依据；原严格报告门限保持不变。

## 导出、测试与运行

以下命令从 `ZqhjGame` 仓库根目录执行；先完成 [QUICKSTART.md](QUICKSTART.md) 中的环境准备。导出到未存在的新目录，不能覆盖正在运行或已记录成绩的包。

```powershell
.\.venv-learning\Scripts\python.exe -m unittest discover -s learning -p test_capture.py
.\vision.cmd verify
.\run.cmd test

$package = "artifacts/submission/capture-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\vision.cmd export --weights artifacts/submission/score-v22/vision.pt `
  --patch-appearance --geometry estimated --cooperative-capture `
  --reports-default-on --output $package

.\.venv-learning\Scripts\python.exe tools/check_visual_package.py "$package/agent.py" `
  --output "$package/isolation.json"

$runDir = "artifacts/vision/runs/capture-$(Get-Date -Format yyyyMMdd-HHmmss)-seed101"
.\vision.cmd run --ue-direct --duration 600 --seed 101 `
  --submission "$package/agent.py" --enable-reports --max-photos 400 --output $runDir

# 仅在回合结束且 run.json 标记 completed 后分析
.\.venv-learning\Scripts\python.exe tools/analyze_capture_run.py $runDir `
  --output "$runDir/capture-analysis.json"
.\.venv-learning\Scripts\python.exe tools/analyze_score_run.py $runDir `
  --output "$runDir/score-analysis.json"
```

本次实际候选为 `artifacts/submission/capture-v25/agent.py`，针对性实测目录为 `artifacts/vision/runs/capture-v25-seed101/`，时长为 300 秒。上方 600 秒命令供完整复测，不是 v25 已完成的成绩。训练命令见 [QUICKSTART.md](QUICKSTART.md)；本次修改的是任务协调与相机/导航控制，无需重新训练即可运行。

## 验证与结果

初版检查通过：13 项协同测试、10 项搜索测试、3 项异步测试、5 项几何测试、17 项视觉检查及基础控制检查。修正后增加确认阶段保持搜索的回归，共 14 项协同测试通过。v24 独立包隔离检查确认三机模型私有且在线回调不读写文件，证据：`artifacts/checks/capture-v24-isolated.json`。

| 正式实验 | 时长 / seed | 分数 | 报告 | 清除 | 惩罚 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| score-v22 已验证基线 | 599.9167 秒 / 101 | 9.06 | 2 | 0/3 | 0 | 坐标精度分，无捕获 |
| capture-v23 首轮 | 600.0 秒 / 101 | 0 | 0 | 0/3 | 0 | 未发起接应任务，确认阶段失败 |
| capture-v24 搜索航迹修正 | 599.95 秒 / 101 | 0 | 0 | 0/3 | 0 | 最大连续定位计数为 1，仍未发起任务 |
| capture-v25 云台稳定窗口 | 299.9667 秒 / 101 | 9.27 | 2 | 0/3 | 0 | 两次召集与确认成功，均在共同观察前中断 |

v23 三机只有 SEARCH/VERIFY 状态，各自 65、42、53 个 VERIFY 日志样本；均无任务、无接应确认、无本地联合观察，`fast_geo_hits` 最大值均为 0。三架飞机的推理异常、异步丢弃均为 0，约 99.38% 日志记录中可见两名队友；因此首轮瓶颈位于视觉确认而非通信握手。官方三个目标 `coop_ticks=0`。

赛后查看公开照片，发现多处高置信框落在树木、阴影或建筑边缘；不能因为网络自信就视作真目标。首轮尚未确认就切换盘旋的代码会改变航迹和相机姿态，有打断地面估计及偏离搜索区域的风险。v24 只修改此项：VERIFY 继续搜索飞行，可靠确认后才进入任务盘旋；是否改善由第二轮结果检验，不把这一推断当作已经证明的因果关系。

首轮证据：`artifacts/checks/capture-v23-101-capture-analysis.json`、`capture-v23-101-analysis.json`、`capture-v23-101-judge-analysis.json`，以及[公开照片检查图](../artifacts/checks/capture-v23-public-review.jpg)。外部裁判记录仅用于赛后分析，不向在线策略提供输入。

为保持交接目录只包含当前候选，v23、v24 失败中间包、完整回合及原始外部跟踪文件分别可恢复地归档于本机 `.local-archive/capture-development/failed-v23/`、`failed-v24/`，不加入 Git。各轮原始官方评分的逐字节副本 `artifacts/checks/capture-v23-evaluation.json`、`capture-v24-evaluation.json` 和对应 `capture-vXX-package.json` 来源清单随诊断摘要保留。

v24 仍未建立任务，三机 `fast_geo_hits` 最大值为 1、0、1，且推理异常和异步丢弃均为 0。公开记录显示 20003 在约 230 秒时保持车辆身份与运动关联，但云台调整期间定位预算从 84.70 米升到 116.58 米，连续定位被清零；20001 约 405 秒则在一次有效定位后丢失候选。详细相邻帧见 `artifacts/checks/capture-v24-confirmation-windows.json`，配套[公开照片](../artifacts/checks/capture-v24-confirmation-review.jpg)。这些现象支持优先检查稳定观察窗口，但两次单 seed 回合不足以证明因果或泛化效果。

v25 新增云台保持必须按时结束、定位通过立即结束的回归，协同测试共 15 项通过，包隔离检查见 `artifacts/checks/capture-v25-isolated.json`。正式回合、短回合和合成测试分开记录。

## 当前接应为什么没有捕获

| 发现机 → 接应机 | 发起 / 确认时刻 | 接应机距图像估计目标 | 释放时刻与原因 |
| --- | --- | --- | --- |
| 20003 → 20001 | 228.87 / 229.88 秒 | 约 1174 米 | 241.55 秒，视觉恢复超时 |
| 20001 → 20003 | 263.73 / 264.80 秒 | 约 573 米 | 273.33 秒，视觉恢复超时 |

两次任务中发现机的有效视觉均只保持了少量采样帧，接应机没有独立确认目标。第一架接应机即使按 32 米/秒直线飞到 350 米范围，也约需 26 秒，而任务约 13 秒就因失去视觉释放；第二次还受转向、飞行和相机搜索影响。距离来自公开队友位姿与图像定位估计，不是隐藏真值。第三架 20002 持续搜索，未参加两次跟踪任务。

接下来首先改进发现机的持续视觉保持和接应机的目标重获，检查转入盘旋后的云台视角、候选尺度、丢帧与像素轨迹关联。不能只延长失联超时，让飞机追逐越来越旧的坐标。第三架的多目标候选队列仍未实现。

本地联合观察最大值与官方三个目标 `coop_ticks` 均为 0；外部约 5 Hz 的赛后采样也没有有效双机共同帧。三机推理异常及异步丢弃均为 0。原始 `acknowledged` 标记在任务释放后可能残留，赛后统计只将活动成员的 APPROACH/TRACK_PAIR/RECOVER 状态计为接应确认，不能直接累计该标记所有出现次数。

原始评分：`artifacts/vision/runs/capture-v25-seed101/official/coop_decoy_1789204480.evaluation.json`。分析：`artifacts/checks/capture-v25-101-capture-analysis.json`、`capture-v25-101-analysis.json`、`capture-v25-101-judge-analysis.json`、`capture-v25-recruitment-distances.json`。[任务关键照片](../artifacts/checks/capture-v25-missions-review.jpg)对照发现、失去有效视觉及接应阶段；[公开照片与航迹回放](../artifacts/checks/capture-v25-replay.html)可离线打开。v25 与 v22 回合时长不同，不能据此认定新版本整体优于基线。
