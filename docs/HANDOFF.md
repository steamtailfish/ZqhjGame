# 团队交接总览

更新日期：2026-09-13。仓库为 GitHub `steamtailfish/ZqhjGame`，主分支 `master`，Git 根目录为 `ZqhjGame/`。本次发布采用 **capture-v31**，当前 `src/` 精确对应其 17 个导出模块。历史发布 v26 与冻结 v22 基线保留。

## 1. 当前结果

| 项目 | 已验证结果与边界 |
| --- | --- |
| 完整回合 | seed101，请求 600 仿真秒，官方记录至 599.9833 秒 |
| 总分 | 28.33，当前最高单次成绩，尚非多 seed 稳定成绩 |
| 坐标报告 | 4 次，RMSE 6.5411588239 米 |
| 捕获 | 0/3，官方 `passed=false` |
| 协同采样 | 官方目标 10002 / 10003 / 10001 的 `coop_ticks` 为 0 / 21 / 62，后两个各重置一次 |
| 惩罚 | 本回合 0，不代表全面安全性证明 |
| 未完成 | 接应机独立有效视觉与持续 20 秒同目标双机捕获 |

原始结果见 [v31 evaluation](../artifacts/submission/capture-v31/evaluation.json)。分数来自坐标精度，捕获与完成时间项为 0；合作 tick 是采样数量，不能直接当作秒数。历史发布 v26 为 18.67 分、4 报告、0 捕获；v22 为 9.06 分、2 报告、0 捕获。不同回合的时序和诱饵差异使单次分差不足以证明因果收益。

本次提供冻结包及原始评分；约 1 GB 的 v31 原始运行记录和照片仅本地保留。队友无需旧 run 即可核查评分、加载模型并重跑完整比赛。详细回放和逐帧复盘仍需要原始记录，不能声称仅靠评分文件可以恢复。

## 2. 在线方法

1. 每机独立读取公开 RGB 照片与位姿，单个私有 worker 约每 0.5 仿真秒处理新照片，并绑定原照片及接收时刻。
2. 灰度轮廓产生车辆候选；64×64 局部 CNN 判断真车、诱饵和背景。使用原 appearance-v3 权重，没有重训。
3. 背景光流和单应变换支持像素关联；自机运动估计局部地面平面，射线投影得到地理坐标。已绑定轨迹有有限身份记忆，原类别概率不改写，新任务及坐标报告仍需严格证据。
4. 三机分区条带搜索。发现机确认后召集预计到达较快的空闲队友，第三架继续搜索。任务中心仅由发现机视觉及其合法广播更新；接应机需自身照片确认，并与独立发现机参考一致。
5. 搜索 FOV 50°、活动双机 FOV 30°。世界视线云台补偿机头转向；远距离接应先径向接近，近圈启用四秒圆弧目标和匹配曲率转率，再经解析固定翼基元与安全筛选执行。
6. 坐标报告独立要求连续真车身份、运动、定位一致性及时效。报告不等于捕获，瞄准和预测也不等于自身已看见目标。

Gou 和 YOPO 提供引导策略、运动基元及轨迹代价的设计参考。当前未启用 Nano 或 YOPO 学习评分头，没有运行论文完整强化学习或图像到轨迹端到端训练。技术细节见 [技术报告](TECHNICAL_REPORT.md) 与 [协同说明](COOPERATIVE_CAPTURE.md)。

## 3. 代码分工

| 路径 | 职责 |
| --- | --- |
| `src/zqhj_patch_vision.py` | 轮廓、裁剪、局部三类 CNN |
| `src/zqhj_async.py`、`src/zqhj_photo_entry.py` | 私有异步推理、像素关联、云台和感知时序 |
| `src/zqhj_visual_geometry.py` | 单应变换、平面拟合及定位误差预算 |
| `src/zqhj_score_search.py`、`src/zqhj_team.py` | 条带搜索与严格坐标报告 |
| `src/zqhj_capture.py` | 任务状态、身份记忆、独立同目标参考、接应及云台 |
| `src/zqhj_comm.py`、`src/zqhj_cooperation.py` | 合法通信、角色与过期管理 |
| `src/zqhj_planner.py` | 四秒运动基元、近圈圆弧目标与安全代价 |
| `tools/train_vehicle_appearance.py` | 当前局部 CNN 离线训练 |
| `tools/export_visual.py` | 合并 17 个模块、打包模型与 manifest |
| `tools/run_perception_probe.py`、`tools/vision_runner.py` | UE/SDK 启动与回合记录 |
| `learning/guidance.py`、`src/zqhj_inference.py` | 保留的引导学习研究，非当前运行规划器 |

修改 `src/` 不会改变已导出的 `--submission artifacts/submission/capture-v31/agent.py`。必须另导出新目录并显式选择新包；已评分代码、模型与原始 evaluation 不覆盖。包内发布说明和元数据已更新，历史本地说明另有备份，不改写实际算法成绩。

## 4. 接手与验收

1. 按 [资产清单](ARTIFACT_HANDOFF.md) 完成 Git LFS 下载和训练图片迁移（仅训练需要）。官方发行包与虚拟环境单独准备。
2. 按 [QUICKSTART](QUICKSTART.md) 核验包哈希、源码对应关系和相关检查，再运行冻结 v31。
3. 保存新回合官方 JSON、代码和模型哈希、完整命令、环境、seed、时长、分数、报告数、RMSE、捕获与惩罚。相同 seed 也不保证恰好复现 28.33。
4. 从 [问题清单](KNOWN_ISSUES.md) 选一个假设，修改后另导出、测试、评估。优先用官方首次真实清除验收捕获链路。

```powershell
git status --short --branch
git pull --ff-only
git switch -c codex/your-change
```

保持本机未提交工作，不执行全局 reset/clean 或进程清理。v22 的 `V22_ASSETS.json` 只覆盖基线及训练依赖；v31 的哈希和发布范围见资产清单。检查命令统一见 QUICKSTART。本次 242 项检查、独立包隔离与重导出字节一致性验证通过，60 个受检官方文件未改变；见 [发布验证](../artifacts/checks/release-v31/validation.json)。这些检查不代替比赛成绩。

## 5. 数据与规则边界

在线只用 `obs.self`、`obs.comm_inbox`、`obs.briefing` 和实例状态；队友信息经合法广播取得。禁止把 Redis、隐藏目标路线、裁判真值、其他 Agent 对象或磁盘截图作为在线输入。外部裁判记录仅供赛后诊断，不作为身份训练标签。规则与接口见 [SDK_CONTRACT](SDK_CONTRACT.md)、[ENVIRONMENT_AUDIT](ENVIRONMENT_AUDIT.md) 及 [AGENTS](../AGENTS.md)。

现有 CNN 数据包含 35 真车、17 诱饵、709 背景局部样本，训练 2400 步；34/34 受控验证不证明正式场景泛化。旧 Word 是 v22 技术快照，当前仓库 Markdown 技术报告已更新为 v31。
