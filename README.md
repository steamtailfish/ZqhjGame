# ZqhjGame

红枫 2026 赛题二的多无人机视觉协同代码。**当前发布与推荐运行版本为 capture-v31：seed101，请求 600 仿真秒、记录 599.9833 秒，单次取得 28.33 分、4 次坐标报告、RMSE 6.5411588239 米、0 惩罚、0/3 捕获。** 官方 `passed=false`，尚未完成双机连续 20 秒捕获，也未验证多 seed 稳定性。

当前方法是轮廓候选 → 64×64 局部 CNN 分类 → 图像运动关联与局部地面定位 → 三机搜索、合法广播双机接应和解析固定翼规划 → 严格坐标报告。参考了 Gou 的围捕策略引导和 YOPO 的运动基元/代价思想，但当前没有启用 Nano 跟踪器或 YOPO 学习评分头，也不是图像到轨迹的端到端网络。

本次发布的 `src/` 与冻结 v31 的 17 个导出模块一致。v31 在活动成员进入目标环附近时，采用四秒后的圆弧终点及匹配曲率转率，继续使用 appearance-v3 权重，没有重新训练。官方已出现部分共同跟踪采样，接应机仍未建立独立有效视觉，尚无捕获分。完整证据以包内 [evaluation.json](artifacts/submission/capture-v31/evaluation.json) 为准。

历史发布 v26 为 18.67 分、4 报告、0 捕获；冻结 v22 基线为 9.06 分、2 报告、0 捕获。历史结果及 v22 导出、训练依赖保持，不能将单次最高分视为稳定提升。

## 队友从这里开始

| 文档 | 用途 |
| --- | --- |
| [安装、运行与训练](docs/QUICKSTART.md) | 从仓库根目录执行的 PowerShell 命令 |
| [交接总览](docs/HANDOFF.md) | 方法、代码分工与验收流程 |
| [资产清单](docs/ARTIFACT_HANDOFF.md) | Git LFS、冻结哈希和训练数据迁移 |
| [已知问题](docs/KNOWN_ISSUES.md) | 捕获、感知与运行限制 |
| [技术报告](docs/TECHNICAL_REPORT.md) | 当前 v31 的技术实现与论文适配边界 |
| [双机接应说明](docs/COOPERATIVE_CAPTURE.md) | 状态机、近圈圆弧与同目标约束 |
| [当前状态](STATUS.md) | 发布与验证记录 |

## 环境与运行

Git 根目录就是 `ZqhjGame/`。将它放在另行准备的官方 Windows UE 发行包内：

```text
hf2026-sim-windows/
├─ competition/             # 官方 SDK / 场景 / 裁判
├─ python/                  # 官方解释器
├─ ue-renderer/              # UE 图像环境
├─ opensim-sim.exe
└─ ZqhjGame/                 # 本仓库，git 命令在这里执行
   ├─ src/                  # 在线算法，当前对应 v31
   ├─ learning/             # 学习研究与回归检查
   ├─ tools/                # 训练、导出、运行及赛后分析
   ├─ docs/
   └─ artifacts/            # 权重与冻结结果，使用 Git LFS
```

先执行 `git lfs pull`，再按 [QUICKSTART](docs/QUICKSTART.md) 重建 `.venv-learning` 并校验资产。本次上传 v31 包内代码、模型、依赖、发布说明、manifest 和原始评分；约 1 GB 的 v31 原始录图与运行目录仅本地保留。**运行冻结包、核查历史得分或重跑比赛不需要旧录图。** 官方 SDK/UE 和本机虚拟环境需单独准备。

准备完成后，在本仓库根目录运行：

```powershell
$runDir = "artifacts/vision/runs/capture-v31-$(Get-Date -Format yyyyMMdd-HHmmss)-seed101"
.\vision.cmd run --ue-direct --duration 600 --seed 101 `
  --submission artifacts/submission/capture-v31/agent.py `
  --enable-reports --max-photos 400 --output $runDir
```

必须等回合完成，再读取 `$runDir/official/*.evaluation.json`。相同 seed 也可能受诱饵与闭环采样时序影响，不能保证重跑恰好 28.33 分。600 秒是仿真时间；不要同时运行两场 UE / Redis 回合。

## 开发原则

- 冻结 v31、历史 v26 和 v22 的代码、模型及原始评分保持原样；开发修改 `src/` 后导出到新目录。
- 在线仅使用本机公开照片/位姿/briefing、合法通信和实例状态；官方环境只读，裁判数据仅供赛后分析。
- 每次评估记录代码和模型哈希、seed、时长、分数、报告数、RMSE、捕获数与惩罚。
- 当前优先解决接应机独立确认和连续视觉保持，以官方真实捕获为验收标准。
