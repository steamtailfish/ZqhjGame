# 三机搜索与双机接应：capture-v26

更新于 2026-09-12。当前运行包为 `artifacts/submission/capture-v26/`，参考 Gou 围捕策略引导与 YOPO 运动基元思想，采用局部 CNN 视觉分类、运动几何定位、合法广播和解析固定翼规划。本轮没有重训，也没有启用 YOPO 学习评分头，不是图像到轨迹的端到端网络。

## 正式结果

**seed101，600 秒请求 / 599.9667 秒记录：18.67 分、4 次坐标报告、RMSE 9.6671 米、0 惩罚、0/3 清除，`passed=false`。** 相比已保留的 v22 完整回合 9.06 分，本轮分数更高；这是一次单 seed 结果，不能证明稳定提升或泛化。

| 验证项 | v26 实际结果 |
| --- | --- |
| 分数来源 | 精度维度 62.23 × 0.30 = 18.67；捕获与时间维度均为 0 |
| 官方共同跟踪 | 目标 10001 / 10002 / 10003 的 `coop_ticks` 为 35 / 124 / 0 |
| 连续捕获 | 前两个目标各有一次计时重置，最终均未清除 |
| 召集 | 三次任务均完成接应确认，随后因有效视觉恢复超时释放 |
| 本机视觉证据 | 三机最长连续正样本跨度为 1.05 / 3.68 / 2.68 秒，本地联合计时仍为 0 |
| 推理可靠性 | 三机各 1132 次推理，推理异常与异步丢弃均为 0 |

这里的官方目标编号仅用于解释赛后评分；在线任务编号始终是发现机 UID 与本机序号。`coop_ticks` 是裁判采样数量，不能直接换算为秒或宣称达到捕获。与 v22/v25 的共同跟踪采样为 0 相比，本轮已出现实际双机有效跟踪，但仍未维持 20 秒。

原始评分：[evaluation](../artifacts/vision/runs/capture-v26-seed101/official/coop_decoy_1789219639.evaluation.json)。运行包中的 `evaluation.json` 是原样副本。[任务分析](../artifacts/checks/capture-v26-101-capture-analysis.json)、[视觉与上报分析](../artifacts/checks/capture-v26-101-analysis.json)、[关键照片](../artifacts/checks/capture-v26-review-01.jpg)、[照片与航迹回放](../artifacts/checks/capture-v26-replay.html)均由已结束的回合生成。

赛后独立约 5 Hz 裁判输入采样进一步定位到两段共同观察：263.97–273.00 秒（20001/20003，样本跨度约 9.03 秒）及 415.15–417.62 秒（20001/20002，约 2.47 秒）。这些跨度不是官方精确累计时间，见[共同观察窗口](../artifacts/checks/capture-v26-101-joint-windows.json)及[归一化裁判诊断](../artifacts/checks/capture-v26-101-judge-analysis.json)。第一段已不足规则所需 20 秒。

## 本轮改了什么

v25 的发现机转入盘旋时可按约 30°/秒转向，而代码将云台 pan 每次调整限制为 6°，约 12°/秒。公开照片显示车辆移向边缘后丢失，接应机也在缓慢转动相机期间浪费了观察时间。

v26 在已经确认的双机任务中，使用新鲜图像定位或合法通信更新的目标位置、地面高度，以及当前自机位置和航向，直接计算世界视线并转换为相对云台角度。这同时补偿机身转弯和位移，使接应机迅速指向广播位置。重复照片不会重复积分像素误差。`point_gimbal` 接受朝向；SDK 内部 `auto_track` 的角速度配置不是本命令的逐步限制。

本轮在线源码只改变 `zqhj_capture.py` 的相机指向分支，模型权重与其他模块相同，见[修改范围校验](../artifacts/checks/capture-v26-change-scope.json)。SEARCH/VERIFY、识别和报告门限保持不变。快速瞄准不构成本机视觉确认，不会直接产生坐标报告。

v25 原有的定位稳定窗口继续保留：运动已确认而连续定位尚未确认时，最多保持云台 1.5 秒；定位通过或时间到即结束，同一像素轨迹不会反复续期。

## 搜索与协同流程

| 状态 | 行为 |
| --- | --- |
| SEARCH | 三架飞机按公开区域分工搜索；已有双机任务时第三架继续搜索 |
| VERIFY | 沿原搜索航迹积累身份、运动和定位证据，最多 8 秒；尚未确认时不召唤队友 |
| OFFER | 可靠发现机选择预计到达最快的空闲队友，广播任务 |
| APPROACH | 接应机确认后前往目标；相机指向公开估计位置，独立寻找车辆 |
| TRACK_PAIR | 两机各有新鲜本机照片，并与同一任务匹配，才累计本地联合时间 |
| RECOVER | 失去视觉后恢复；中断超过 2 秒重置本地联合计时 |
| RELEASE | 恢复/接应超时或本地联合观察达到 25 秒后释放，再回到搜索 |

本机实际加载的裁判 `competition/sdk/_vendored/coop_eval.py` 按捕获 50%、逐目标坐标精度 30%、全部任务完成时间 20% 加权。两机对同一真实目标连续有效跟踪 20 秒才清除，短中断容忍 2 秒。未上报的目标精度为 0，已报告目标按自己的 RMSE 与 120 米归零距离计算，再对三个目标平均。重复报告同一辆车不能替代另外两辆车的搜索覆盖。

三次任务分别为 20003→20001（230.40–243.13 秒）、20001→20003（263.22–272.73 秒）、20002→20001（412.25–428.70 秒）。第三次由继续搜索的飞机新发起。本地计时与裁判判定采用不同证据，前者始终标记 `judge_confirmed=false`。

## 身份、通信和飞行约束

- 召集需连续至少 3 帧真车概率 ≥0.95、类别分差 ≥0.9，通过运动验证及至少两次一致地理估计，定位预算 ≤110 米。维持观察的当前帧门限为概率 ≥0.9、分差 ≥0.8。
- 接应机必须用自己的照片验证。初次绑定距离门限 80 米，维持门限 160 米；绑定同时检查本机像素轨迹和任务编号。照片接收年龄 ≤0.8 秒，不等于已验证的拍摄时间。
- 广播为 49 个 ASCII 字节、每秒最多 2 次，包含发现机/接应机、阶段、目标位置、速度、地面高度和观测年龄，符合 50 字节/4 Hz 限制。
- 接应预算为 45–160 秒；8 秒未确认可改选队友；所有有效视觉丢失 8 秒释放；单次任务最多 200 秒。
- 搜索参考速度 35 米/秒，远距离接应 32 米/秒，近目标 18 米/秒；期望盘旋半径 320/360 米。实际动作经固定翼规划器与安全约束筛选，保持原 200 米机间距离底线。
- 在线只使用本机公开 RGB/位姿/briefing、合法广播和实例状态。官方 SDK、场景和裁判不修改，外部裁判记录只用于赛后诊断，不能反馈在线或作为身份训练标签。

## 仍然限制得分的问题

相机修正后已经出现官方共同跟踪，但本地可靠视觉仍短于接应所需时长。三次最终视觉中断都紧接任务附近候选被分类为诱饵：20003 在 235.23 秒、20001 在 264.85 秒、20002 在 420.73 秒，投影位置距公开任务估计仅约 5.6、8.7、3.8 米。最后一次车辆仍接近画面中心，说明相机补偿已经执行；分类翻转会立即清空候选并重置像素轨迹和运动证据。这些是公开记录关联，分类概率不是真实身份标签。下一轮考虑已确认轨迹的短时身份迟滞和空间/运动重获，仍需正式回合验证；不能直接取消诱饵过滤或无限延长旧坐标租期。

近正下视时，保持同一地面点仍可能让画面朝向快速旋转。20002 在 412.25–412.77 秒发生大幅 pan 换向，随后光流匹配不足，413.85 秒像素轨迹重置；416.52 秒曾恢复绑定。世界视线稳定并不保证图像关联稳定，这也是下一轮需要处理的环节。

远距离尺度也有限制：v25 已保存照片的透视估算显示，1174 米距离、50°视场下车辆长边约 4 像素，低于当前轮廓候选尺寸门限。接应机需要继续飞近；当前接应引导在 650 米以内过早进入盘旋切线，是下一项待验证改动。此结论是离线几何估算，不代表缩小视场即可准确识别。

当前同时只保留一个共享双机任务，第三架尚无多目标候选队列。缺少多 seed 结果、未见场景验证，公开照片的真实拍摄时刻及地面估计仍有误差。

## 运行、训练与验证命令

以下均在 `ZqhjGame` 仓库根目录的 PowerShell 执行。环境和现有外观模型训练步骤见 [QUICKSTART.md](QUICKSTART.md)。本轮是控制修改，无需重新训练。

```powershell
# 检查当前源码
.\.venv-learning\Scripts\python.exe -B -X utf8 -m unittest learning.test_capture learning.test_score_search learning.test_async_vision learning.test_visual_geometry learning.test_judge_trace

# 直接运行已经验证的 v26 冻结包
$runDir = "artifacts/vision/runs/v26-$(Get-Date -Format yyyyMMdd-HHmmss)-seed101"
.\vision.cmd run --ue-direct --duration 600 --seed 101 `
  --submission artifacts/submission/capture-v26/agent.py `
  --enable-reports --max-photos 400 --output $runDir

# 必须等上面的回合结束
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/analyze_capture_run.py $runDir --output "$runDir/capture-analysis.json"
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/analyze_score_run.py $runDir --output "$runDir/score-analysis.json"
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/build_capture_review.py $runDir --output "$runDir/review"

# 修改 src 后导出新包，不覆盖冻结包
$package = "artifacts/submission/capture-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\vision.cmd export --weights artifacts/submission/score-v22/vision.pt `
  --patch-appearance --geometry estimated --cooperative-capture `
  --reports-default-on --output $package
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/check_visual_package.py "$package/agent.py" --output "$package/isolation.json"
```

21 项协同、10 项搜索、3 项异步、5 项几何测试和 9 项离线时间轴测试通过；[独立包隔离检查](../artifacts/checks/capture-v26-isolated.json)确认三机模型私有、在线回调无文件 I/O。离线时间轴从正式首帧日志恢复起点，保留原始时间与舍入误差，不硬编码时区偏移。软件检查不代替正式成绩。

仅保留当前 v26 候选、v22 冻结基线及当前训练依赖。v25 旧包、旧回合和原始裁判 trace 可恢复归档在本机 `.local-archive/capture-development/previous-v25/`，不加入 Git；原始评分副本 `artifacts/checks/capture-v25-evaluation.json`、来源包清单 `capture-v25-package.json` 和分析摘要保留。v25 是 300 秒 / 9.27 分实验，不能与 v26 完整回合直接作因果对照。v23/v24 失败实验已归档，当前入口不再指向旧包。
