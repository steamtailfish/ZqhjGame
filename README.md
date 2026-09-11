# ZqhjGame

红枫 2026 赛题二的多无人机视觉协同代码。**当前已验证基线为 score-v22：正式场景 seed101、600 秒回合取得 9.06 分，2 次坐标报告，0/3 目标清除，0 惩罚，定位 RMSE 11.27 米。** 这是一次非零成绩，尚未实现双机持续捕获或稳定高分。

当前实际方法：轮廓候选 → 64×64 局部 CNN 真假/背景分类 → 图像运动关联与局部地面定位 → 条带搜索、广播协同和解析轨迹规划 → 严格短轨迹坐标上报。参考了 Gou 围捕策略引导和 YOPO 运动基元/代价思想，但 **v22 没有使用 YOPO 学习评分头，也不是图像到轨迹的端到端网络**。

## 队友从这里开始

| 文档 | 用途 |
| --- | --- |
| [交接总览](docs/HANDOFF.md) | 当前代码结构、方法、结果、开发与验收流程 |
| [安装、运行与训练](docs/QUICKSTART.md) | 从本仓库根目录执行的 PowerShell 命令 |
| [资产交接清单](docs/ARTIFACT_HANDOFF.md) | 克隆后还缺什么、冻结包哈希、数据路径迁移 |
| [已知问题与下一步](docs/KNOWN_ISSUES.md) | 捕获失败、识别/定位风险、工具限制与优先级 |
| [首个非零成绩记录](FIRST_SCORE.md) | v22 实测依据、历史对比与原始产物路径 |
| [版本历史](STATUS.md) | 按版本保留的开发与验证记录；旧章节不代表当前状态 |

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
   └─ artifacts/               # 权重、冻结包、数据、日志，不提交
```

`.gitignore` 忽略整个 `artifacts/`。**仅执行 `git clone` 不会获得已得分权重、提交包或训练数据**，也不会获得官方 SDK / UE。先按[资产交接清单](docs/ARTIFACT_HANDOFF.md)同步所需文件，再执行[快速开始](docs/QUICKSTART.md)。

环境与冻结包齐备后，从本仓库根目录执行一次完整回合：

```powershell
$runDir = "artifacts/vision/runs/v22-$(Get-Date -Format yyyyMMdd-HHmmss)-seed104"
.\vision.cmd run --ue-direct --duration 600 --seed 104 `
  --submission artifacts/submission/score-v22/agent.py `
  --enable-reports --max-photos 500 --output $runDir
```

seed104 是复测示例，不是已验证成绩。必须等回合结束，读取 `$runDir/official/*.evaluation.json`；中途显示分数、进程退出、检测 mAP 和 `OBSERVE` 状态都不能替代最终比赛结果。不要同时运行两场 UE / Redis 回合。

## 开发原则

- 保留 `artifacts/submission/score-v22/` 原样；修改源码后导出到新的版本目录并重新评估。
- 在线仅使用本机公开照片/位姿/briefing、合法广播和实例状态。官方文件只读，裁判诊断仅在回合结束后进行。
- 每次结果记录代码及权重哈希、seed、仿真结束时间、总分、报告数、清除数、惩罚和 RMSE。
- 当前优先补齐双机对同一真目标持续 20 秒的实际捕获，具体任务见[已知问题](docs/KNOWN_ISSUES.md)。

历史学习分支见 [TRAINING_AND_INFERENCE.md](TRAINING_AND_INFERENCE.md)，历史 YOLO 视觉路线见 [VISION_TRAINING_AND_INFERENCE.md](VISION_TRAINING_AND_INFERENCE.md)。它们保留了不同版本的模型和门限；运行 v22 请以本页、交接文档和 [FIRST_SCORE.md](FIRST_SCORE.md) 为准。
