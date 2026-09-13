# 三机搜索与双机接应：capture-v31

更新日期：2026-09-13。当前发布入口为 `artifacts/submission/capture-v31/agent.py`，`src/` 对应其 17 个导出模块。方法是局部 CNN、图像运动几何、合法广播及解析固定翼规划；未启用 Nano 或 YOPO 学习评分头，本轮没有重训。

## 正式结果与发布范围

**seed101，请求 600 仿真秒、记录 599.9833 秒：28.33 分、4 次坐标报告、RMSE 6.5411588239 米、0 惩罚、0/3 捕获，passed=false。** 原始评分随包提供：[evaluation.json](../artifacts/submission/capture-v31/evaluation.json)。

| 项目 | v31 实测 |
| --- | --- |
| 得分 | 精度维度 94.44，按 0.30 权重计入总分；捕获及完成时间维度为 0 |
| 官方共同跟踪 | 目标 10002 / 10003 / 10001 的 coop_ticks 为 0 / 21 / 62，后两个各重置一次 |
| 本机可靠视觉 | 发现机最长有效样本跨度约 10.15 秒；接应机未建立独立 own_visual |
| 捕获结论 | 尚无连续 20 秒同目标双机捕获，不能将合作采样或报告称为捕获 |

官方目标编号只用于赛后结果说明，在线任务编号为发现机 UID 与本机序号。coop_ticks 是采样数量，不能直接换算为持续秒数。历史发布 v26 为 18.67 分，v22 基线为 9.06 分，均未捕获；28.33 只是当前最高单次结果，尚未证明稳定改进。

本次提供包内代码、模型、依赖、发布说明、manifest 和原始评分；约 1 GB 的旧 run 与录图仅本地保留。加载、查分和重新评估无需旧 run；逐帧复盘仍需原始记录。

## v31 新增近圈圆弧引导

固定翼接近目标环后，原四秒直线切向终点可能使目标代价偏好直行，不能持续表达环绕曲率。v31 仅调整近圈规划：活动成员与目标环的半径偏差不超过 60 米、接应已结束径向接近时，规划目标改为四秒后的逆时针圆弧终点，并增加 `-degrees(cruise_speed / radius)` 的航向转率候选。

发现机和接应机期望半径分别为 320 / 360 米。以 18 米/秒计算，对应转率约 −3.223 / −2.865 度/秒。原转率与速度候选保留，新候选仍经过边界、障碍与队友间距筛选。该候选表达理想运动学；实际命令仍为基于首步航向构造的前方 300 米航点，不能把理想圆弧或模式次数当作真实稳定盘旋。

圆心使用当前公开任务点，未加入移动圆心速度前馈。搜索、初始验真、任务点更新权限、云台、模型和报告门限保持此前已验证逻辑。接应实际到达与减速仍存在时机问题，下一步应与独立视觉持续时间一起验收。

## 搜索与协同流程

| 状态 | 行为与证据 |
| --- | --- |
| SEARCH | 三机按公开任务边界分区条带搜索；已有双机任务时第三架继续搜索 |
| VERIFY | 沿搜索航迹积累身份、运动和定位证据；未确认不能召集队友 |
| OFFER | 发现机可靠确认后选择预计到达较快的空闲队友并广播 |
| APPROACH | 接应机接受任务、径向接近并瞄准公开预测点；必须通过自己的照片确认 |
| TRACK_PAIR | 双机各有新鲜观测，且与独立发现机参考满足同目标关联后，累计本地联合时间 |
| RECOVER | 短时失视尝试恢复；超过 2 秒中断重置本地联合时间 |
| RELEASE | 恢复或接应超时、任务结束后释放，返回搜索 |

本地联合时间不是裁判确认，始终不能替代引擎 K=2、持续 20 秒、短中断容忍 2 秒的清除条件。当前同一时刻只保留一个共享双机任务，尚无多目标候选队列或已验证的接应接管机制。

## 身份、通信与相机

- 新任务需连续高置信真车身份、运动证据和一致定位；接应机不能继承发现机身份直接宣称看见。
- 已绑定轨迹保留有限身份记忆：预测位置 25 米匹配、投影面积比 0.35–2.85、连续匹配间隔不超过 2 秒、最近强真车身份不超过 3 秒。原始类别与概率不改写；三次强诱饵反证跨至少 1 秒可撤销，歧义和过期也会清除绑定。重复图片不增加证据。
- 任务中心只由发现机真实视觉及其合法广播更新。双机按观测时刻对齐位置，与独立发现机参考比较，参考及接应观测需在 0.8 秒内，差距不超过 25 米；接应自己的错误点不能循环污染中心再通过验证。
- 捕获广播为 49 个 ASCII 字节，最多 2 Hz，包含任务、目标位置/速度、地面高度和观测年龄；符合 50 字节 / 4 Hz 限制。
- 搜索视场 50°，活动双机视场固定 30°。云台用当前自机位姿直接指向任务的世界视线，补偿转弯与平移；任务预测最多外推 3 秒。瞄准或预测不刷新 own_visual。
- 初始定位仍保留最多 1.5 秒相机稳定窗口。所有有效视觉丢失 8 秒后释放，不能无限凭旧坐标维持任务。

接应 APPROACH 在距目标大于 410 米时保持径向接近；有新鲜发现机广播时，引导至目标另一侧的会合位置，没有时引导至公开任务点。搜索参考速度 35 米/秒、接应远段 32 米/秒、近圈 18 米/秒，实际速度仍由飞控响应决定。

## 运行与开发

以下在 ZqhjGame 仓库根目录的 PowerShell 执行；环境、训练数据迁移及检查见 [QUICKSTART](QUICKSTART.md)。直接运行不需要重新训练。

```powershell
$runDir = "artifacts/vision/runs/capture-v31-$(Get-Date -Format yyyyMMdd-HHmmss)-seed101"
.\vision.cmd run --ue-direct --duration 600 --seed 101 `
  --submission artifacts/submission/capture-v31/agent.py `
  --enable-reports --max-photos 400 --output $runDir
if ($LASTEXITCODE -ne 0) { throw '运行失败，先检查 run.json 与日志' }
Get-ChildItem -LiteralPath "$runDir/official" -Filter '*.evaluation.json' |
  ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }

# 修改 src 后导出新候选；不覆盖冻结 v31。
$package = "artifacts/submission/capture-dev-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\vision.cmd export --controller artifacts/submission/score-v22/agent.py `
  --weights artifacts/submission/capture-v31/vision.pt `
  --patch-appearance --geometry estimated --cooperative-capture `
  --reports-default-on --output $package
.\.venv-learning\Scripts\python.exe -B -I tools/check_visual_package.py `
  "$package/agent.py" --output "$package/isolation.json"
```

新候选需独立完成相关回归与正式回合，不继承 28.33 分。在线仅使用自身公开输入和合法广播；裁判记录只能赛后解释结果，不用作在线身份或训练标签。更多问题见 [KNOWN_ISSUES](KNOWN_ISSUES.md)。
