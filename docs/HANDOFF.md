# 团队交接总览

更新日期：2026-09-11。对象：GitHub `steamtailfish/ZqhjGame`，仓库根目录为 `ZqhjGame/`。本文对应 score-v22 冻结基线；这次交接更新只改文档，不改算法、权重或官方环境。

## 1. 当前做到哪里

| 项目 | 已验证结果 / 尚未完成内容 |
| --- | --- |
| 正式成绩 | seed101，请求 600 秒，官方记录到 599.9167 秒；总分 9.06 |
| 定位报告 | 2 次，累计定位 RMSE 11.2691 米 |
| 捕获 | 0/3 清除，三个目标 `coop_ticks` 均为 0；尚未形成裁判有效双机跟踪 |
| 惩罚 | 本回合 0，不代表安全性已被全面验证 |
| 感知运行 | 三机推理异常与异步丢弃均为 0 |
| 泛化与高分 | 未完成多 seed 统计、未见场景验证或稳定高分验收 |
| 端到端学习 | 历史引导学习代码可研究；v22 在线用解析规划，没有接入 YOPO 评分头 |

分数来自精度项：精度维度 30.2，权重 0.3，贡献 9.06；清除和时间维度均为 0。官方 `passed=false`，不可将“拿到分数”称作“完成捕获”。规则要求两架无人机对同一真实目标满足引擎有效跟踪条件并持续 20 秒，短中断容忍 2 秒。坐标上报与捕获分别验收。

原始记录位于 `artifacts/vision/runs/score600-v22-seed101/official/coop_decoy_1789108334.evaluation.json`。冻结包 `baseline_evaluation.json` 是原样副本。二者均不随 Git 克隆；对应哈希见[资产清单](ARTIFACT_HANDOFF.md)。版本对比见 [FIRST_SCORE.md](../FIRST_SCORE.md)。

## 2. 当前在线链路

1. **本机视觉输入**：公开 RGB 照片，实测 1024×768。每机独立模型、独立状态，异步视觉约每 0.5 秒处理新帧。
2. **车辆候选与身份**：灰度轮廓筛选，64×64 裁剪输入轻量 CNN，输出真车、诱饵、背景概率。部署权重为 appearance-v3；当前不是 YOLO 检测网络。
3. **连续关联与定位**：背景光流/单应变换补偿相机运动，关联车辆像素轨迹；本机运动估计局部地面高度，再将射线投影为地理坐标。
4. **搜索与协同**：公开边界内条带搜索，合法广播分配搜索区域与候选接应；导航使用势场引导和固定翼运动基元解析评价。
5. **严格坐标报告**：至少 4 帧连续像素跟踪、最近 3 帧真车概率 ≥0.95 且类别分差 ≥0.9、至少 2 次一致定位；还需运动、俯角、定位预算 ≤110 米、照片接收年龄 ≤0.6 秒及 1 Hz 限频。地理轨迹仍供协同使用，但原地理轨迹报告分支关闭。

v22 的关键是让已满足证据要求的短像素轨迹及时上报，不再等待较慢的导航轨迹确认。降低门限可能重新引入大偏差报告，不能只看报告数量调参。

训练使用人工审核后的 35 个真车、17 个诱饵和 709 个背景局部样本，2400 步；受控留出验证 34/34 正确。同布景、小样本验证不能证明正式地图泛化。appearance-v4 增强实验未部署，待审核 v5 数据未进入当前训练。

## 3. 从哪里改代码

| 路径 | 职责 / 适合接手的内容 |
| --- | --- |
| `src/zqhj_patch_vision.py` | 轮廓候选、局部分类网络、裁剪与三类推理 |
| `src/zqhj_async.py` | 异步推理、结果绑定、每机私有工作线程 |
| `src/zqhj_photo_entry.py` | 视觉与 Agent 串联、像素关联、云台伺服和报告条件 |
| `src/zqhj_visual_geometry.py` | 光流、单应变换、局部地面平面及定位预算 |
| `src/zqhj_score_search.py`、`src/zqhj_team.py` | score 路线入口、队伍条带搜索、严格短轨迹报告 |
| `src/zqhj_cooperation.py`、`src/zqhj_comm.py` | 目标接应与角色、通信编码、过期和限频 |
| `src/zqhj_planner.py` | 势场引导、固定翼候选轨迹、间距与代价筛选 |
| `tools/train_vehicle_appearance.py` | 当前局部外观训练入口 |
| `tools/export_visual.py` | 源码合并、权重打包、生成独立 `EntryAgent` |
| `tools/run_perception_probe.py`、`tools/vision_runner.py` | 离线 UE / SDK 启动、采样、回合结束后保存记录 |
| `tools/analyze_score_run.py` | 回合结束后的结果分析 |
| `learning/guidance.py`、`src/zqhj_inference.py` | 历史 YOPO 式引导学习与推理，非当前得分规划器 |

开发时修改 `src/`；冻结包内 `agent.py` 是导出副本。**修改源码不会改变 `--submission .../score-v22/agent.py` 的在线逻辑**。验证修改必须重新导出到新目录，并在运行参数中选择新包。

## 4. 队友接手顺序

1. 按[资产清单](ARTIFACT_HANDOFF.md)取得官方环境、冻结包和所需训练/诊断数据。
2. 按[快速开始](QUICKSTART.md)重建虚拟环境、核对哈希，先通过不启动引擎的检查。
3. 如需复测，运行原冻结包完整回合，确认本机环境可运行；不要求结果恰好等于 9.06，同 seed 也存在采样和闭环时序差异。
4. 从[问题清单](KNOWN_ISSUES.md)选择一个可独立验收的改动，新建分支并保留 v22。
5. 运行相关回归，导出新包，再做正式回合；同时报告分数、报告误差、捕获与惩罚，避免以单一指标判断改进。

建议按感知识别、相机定位、搜索协同、实验记录划分工作。跨模块改动先约定输入时间、坐标系、候选身份和有效期，避免两侧对同一字段作不同解释。

## 5. Git 与实验记录约定

所有 Git 操作在 `ZqhjGame/` 下进行，不在官方发行包目录另建或嵌套仓库。开始工作先检查工作区，再更新主分支；有本地修改时自行提交或妥善保留，不用 `reset --hard` / `clean` 清理。

```powershell
git status --short --branch
git pull --ff-only
git switch -c codex/your-change
```

每个正式实验记录：Git 提交号、导出包/权重 SHA256、完整命令、环境版本、seed、实际仿真结束时间、官方 JSON 路径、总分、报告数、RMSE、清除数和惩罚。大体积资产按清单另行同步，文档中记录存储位置和哈希。尚未配置自动训练、CI 回归或 GitHub Release 资产下载流程。

不要把本机绝对路径作为队友必须使用的安装位置。本文与 QUICKSTART 的命令统一从仓库根目录执行；旧文档不少命令从发行包父目录执行，复制前先看工作目录。

## 6. 数据与规则边界

在线 Agent 只使用 `obs.self`、`obs.comm_inbox`、`obs.briefing` 和实例自身状态；队友信息必须通过合法通信取得。不得读取 Redis、隐藏目标路线、裁判真值、其他 Agent 对象或截图目录作为策略输入。

`tools/record_judge_trace.py` 等属于外部诊断工具，记录只用于回合结束后解释失败，不作为在线目标 ID、路线或训练标签。受控场景仅修改 `artifacts/` 中的副本，其分数不计为正式成绩。详细规则和接口证据见 [SDK_CONTRACT.md](SDK_CONTRACT.md)、[ENVIRONMENT_AUDIT.md](ENVIRONMENT_AUDIT.md) 与 [AGENTS.md](../AGENTS.md)。

## 7. 本次交接文档的验证

已检查新增文档的相对链接、代码块及 PowerShell 语法，并核对运行、导出、训练入口参数。按 QUICKSTART 的显式 `--controller` 命令实际导出后，`agent.py` 与 `vision.pt` 的 SHA256 与冻结 v22 相同，三机私有模型和回调禁止文件 I/O 的隔离检查通过。证据保存在本机 `artifacts/submission/docs-check-20260911-153850/isolated-check.json`，不随 Git 上传。

已实际执行资产清单中的路径迁移步骤，466 条审核记录及对应训练图片哈希全部通过，生成本机 `accepted-local.jsonl`。未重新训练、未启动正式回合，因此本次只新增交接可用性验证，不新增性能或比赛成绩。
