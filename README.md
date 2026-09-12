# ZqhjGame

红枫 2026 赛题二的多无人机视觉协同代码。**当前推荐复测版本为 capture-v26：正式场景 seed101，请求 600 秒、记录 599.9667 秒，取得 18.67 分，4 次坐标报告，定位 RMSE 9.67 米，0 惩罚，0/3 目标清除。** 官方 `passed=false`，尚未完成双机连续 20 秒捕获，也未验证多 seed 稳定性。

当前实际方法：轮廓候选 → 64×64 局部 CNN 真假/背景分类 → 图像运动关联与局部地面定位 → 条带搜索、广播双机接应和解析轨迹规划 → 严格短轨迹坐标上报。参考了 Gou 围捕策略引导和 YOPO 运动基元/代价思想，但 **当前得分包没有使用 YOPO 学习评分头，也不是图像到轨迹的端到端网络**。

v26 只改进已确认任务的云台指向：用世界视线即时瞄准并补偿机头转向，保留搜索、VERIFY、识别、报告门限和 appearance-v3 权重，没有重新训练。官方首次记录到两个目标的有效协同累计：`coop_ticks` 分别为 35、124，第三个为 0；前两个目标各发生一次重置，仍未连续满 20 秒。18.67 分全部来自坐标精度项，不能称为捕获分。方法、证据和命令见 [双机接应说明](docs/COOPERATIVE_CAPTURE.md)。

score-v22 的完整 600 秒单 seed 基线保持冻结：9.06 分、2 次报告、RMSE 11.27 米、0 惩罚、0 清除。v26 本轮高于该基线；v25 的 300 秒旧回合为 9.27 分，时长不同，不作直接性能比较。

## 队友从这里开始

| 文档 | 用途 |
| --- | --- |
| [交接总览](docs/HANDOFF.md) | 当前代码结构、方法、结果、开发与验收流程 |
| [安装、运行与训练](docs/QUICKSTART.md) | 从本仓库根目录执行的 PowerShell 命令 |
| [资产交接清单](docs/ARTIFACT_HANDOFF.md) | Git LFS 下载、冻结包哈希、数据路径迁移 |
| [已知问题与下一步](docs/KNOWN_ISSUES.md) | 捕获失败、识别/定位风险、工具限制与优先级 |
| [首个非零成绩记录](FIRST_SCORE.md) | v22 实测依据、历史对比与原始产物路径 |
| [当前状态](STATUS.md) | 已验证基线与当前候选的完成情况 |
| [双机接应说明](docs/COOPERATIVE_CAPTURE.md) | 当前协同候选的状态机、通信、验证与运行命令 |

## 仓库与运行环境

**Git 仓库根目录就是 `ZqhjGame/`，不是官方发行包根目录。** 将仓库放在官方 Windows UE 发行包内：

```text
hf2026-sim-windows/              # 官方发行包，单独准备
├─ competition/                 # 官方 SDK / 场景 / 裁判
├─ python/                      # 官方解释器
├─ ue-renderer/                 # UE 图像环境
├─ opensim-sim.exe
└─ ZqhjGame/                    # 本仓库，git 命令在这里执行
   ├─ src/                     # 在线算法
   ├─ learning/                # 引导学习与视觉回归
   ├─ tests/                   # 基础控制回归
   ├─ tools/                   # 离线运行、训练、导出与分析
   ├─ docs/                    # 技术文档与交接说明
   ├─ .venv-learning/          # 本机重建，不提交
   └─ artifacts/               # 当前权重、冻结包、数据、日志，Git LFS
```

`artifacts/` 使用 Git LFS，交接范围为当前 v26、冻结 v22 基线、appearance-v3 及训练依赖和必要诊断。安装 Git LFS 后克隆，执行 `git lfs pull`，再按[资产清单](docs/ARTIFACT_HANDOFF.md)校验。官方 SDK/UE 与本机虚拟环境需单独准备；本机旧实验归档不上传。

环境与冻结包齐备后，从本仓库根目录执行一次完整回合：

```powershell
$runDir = "artifacts/vision/runs/capture-v26-$(Get-Date -Format yyyyMMdd-HHmmss)-seed104"
.\vision.cmd run --ue-direct --duration 600 --seed 104 `
  --submission artifacts/submission/capture-v26/agent.py `
  --enable-reports --max-photos 500 --output $runDir
```

seed104 是复测示例，不是已验证成绩。必须等回合结束，读取 `$runDir/official/*.evaluation.json`；中途显示分数、进程退出、检测 mAP 和 `OBSERVE` 状态都不能替代最终比赛结果。不要同时运行两场 UE / Redis 回合。

## 开发原则

- 保留 `artifacts/submission/score-v22/` 基线与已评估的 v26 包原样；修改源码后导出到新的版本目录并重新评估。
- 在线仅使用本机公开照片/位姿/briefing、合法广播和实例状态。官方文件只读，裁判诊断仅在回合结束后进行。
- 每次结果记录代码及权重哈希、seed、仿真结束时间、总分、报告数、清除数、惩罚和 RMSE。
- 当前优先补齐双机对同一真目标持续 20 秒的实际捕获，具体任务见[已知问题](docs/KNOWN_ISSUES.md)。

当前训练、导出与 v26 推理命令见 [QUICKSTART.md](docs/QUICKSTART.md)，协同方法见 [COOPERATIVE_CAPTURE.md](docs/COOPERATIVE_CAPTURE.md)。保留冻结 v22 供回归；学习研究源码尚未参与当前得分。
