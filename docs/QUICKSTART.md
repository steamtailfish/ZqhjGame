# 安装、运行、训练与复现

适用当前发布 capture-v31；历史发布 v26 与 score-v22 回归基线保留。**本页所有命令均在 `ZqhjGame` 仓库根目录的 PowerShell 中执行**，不是官方发行包根目录。以下复测使用 seed101；已记录的完整 600 仿真秒单次成绩为 28.33 分、4 报告、RMSE 6.5411588239 米、0 捕获、0 惩罚、passed=false。同 seed 不保证相同结果，也不代表多 seed 稳定成绩。

## 1. 首次准备

先单独准备已审计的 OpenSim 2.0.3 Windows UE 发行包，将本仓库放在其中，确保 `../competition/`、`../python/python.exe`、`../ue-renderer/`、`../opensim-sim.exe` 存在。官方环境不在本 Git 仓库内，不要把 SDK、UE 或虚拟环境复制进 Git。

在官方发行包目录下首次克隆（已有仓库就跳过）：

```powershell
git lfs install
git clone https://github.com/steamtailfish/ZqhjGame.git ZqhjGame
Set-Location ZqhjGame
git lfs pull
```

按[资产清单](ARTIFACT_HANDOFF.md)下载并检查 Git LFS 文件。包内 `evaluation.json` 可直接核查原始成绩；约 1 GB 的 v31 原始录图仅本地保留，不是运行或查分依赖。运行现有包不需要训练集，也不需要 `vision.cmd init` 下载/复制旧 YOLO 权重；v31 沿用 appearance-v3，无需重新训练。

新机器使用 Python 3.13 重建项目虚拟环境；开发机验证版本为 3.13.9，CPU Torch 2.7.1。不要拷贝开发机 `.venv-learning`。`py` 需要 Windows Python Launcher；未配置时用本机已安装的 Python 3.13 可执行文件替换第一条命令。

```powershell
py -3.13 -m venv .venv-learning
.\.venv-learning\Scripts\python.exe -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv-learning\Scripts\python.exe -m pip install -r requirements-vision.txt
.\.venv-learning\Scripts\python.exe -m pip check
.\.venv-learning\Scripts\python.exe -c "import sys,torch,cv2,numpy; print(sys.version); print(torch.__version__,cv2.__version__,numpy.__version__)"
```

依赖按现有 `requirements-vision.txt` 安装，包含历史视觉工具需要的 Ultralytics；这不表示当前在线使用 YOLO。若依赖源或版本不可用，记录失败，不要悄悄换版本后声称复现原环境。仓库没有完整的传递依赖锁文件。

## 2. 不启动引擎的检查

确认当前工作目录、v31 代码/权重与冻结 v22 基线哈希。完整期望值见[资产清单](ARTIFACT_HANDOFF.md)。

```powershell
git status --short --branch
Get-FileHash artifacts/submission/capture-v31/agent.py -Algorithm SHA256
Get-FileHash artifacts/submission/capture-v31/vision.pt -Algorithm SHA256
Get-FileHash artifacts/submission/capture-v31/evaluation.json -Algorithm SHA256
Get-FileHash artifacts/submission/score-v22/agent.py -Algorithm SHA256
Get-FileHash artifacts/submission/score-v22/vision.pt -Algorithm SHA256
Get-FileHash artifacts/submission/score-v22/baseline_evaluation.json -Algorithm SHA256

.\run.cmd check
.\run.cmd test
.\vision.cmd verify
.\.venv-learning\Scripts\python.exe -B -X utf8 -m unittest learning.test_capture learning.test_capture_identity learning.test_capture_zoom learning.test_capture_agreement learning.test_capture_approach learning.test_capture_orbit
.\.venv-learning\Scripts\python.exe -B -X utf8 learning/test_score_search.py
.\.venv-learning\Scripts\python.exe -B -X utf8 learning/test_async_vision.py
.\.venv-learning\Scripts\python.exe -B -X utf8 learning/test_visual_geometry.py
.\.venv-learning\Scripts\python.exe -B -X utf8 learning/test_judge_trace.py
```

当前发布的 `src/` 对应 v31 manifest 中的 17 个模块。上列检查应针对这套源码运行；检查结果见 [STATUS](../STATUS.md)。

`run.cmd` 优先使用 `ZQHJ_PYTHON`，其次本项目 `.venv`，最后发行包 `../python/python.exe`；`vision.cmd` 固定使用 `.venv-learning/Scripts/python.exe`。检查通过只证明对应软件链路，不证明比赛得分。

以下隔离检查依赖的固定真车测试照片已随 Git LFS 提供；缺文件时先执行 `git lfs pull`：

```powershell
$checkPath = "artifacts/checks/capture-v31-isolated-$(Get-Date -Format yyyyMMdd-HHmmss).json"
.\.venv-learning\Scripts\python.exe -B -I tools/check_visual_package.py `
  artifacts/submission/capture-v31/agent.py --output $checkPath
```

## 3. 运行已评估的 v31 并读取结果

关闭自己此前启动的重复比赛，确认 6379 端口没有被另一场比赛使用。不要全局结束所有 Python / Redis 进程。先运行冻结包再修改算法，便于区分环境问题和策略退化。

```powershell
$runDir = "artifacts/vision/runs/capture-v31-$(Get-Date -Format yyyyMMdd-HHmmss)-seed101"
.\vision.cmd run --ue-direct --duration 600 --seed 101 `
  --submission artifacts/submission/capture-v31/agent.py `
  --enable-reports --max-photos 400 --output $runDir
if ($LASTEXITCODE -ne 0) { throw '运行失败，先检查本次 run.json 和日志' }

# 必须等待上面的回合结束；同一 PowerShell 会话保留 $runDir。
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/analyze_score_run.py `
  $runDir --output "$runDir/score-analysis.json"
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/analyze_capture_run.py `
  $runDir --output "$runDir/capture-analysis.json"
Get-ChildItem -LiteralPath "$runDir/official" -Filter '*.evaluation.json' |
  ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }
```

600 秒是仿真时间，不是墙钟耗时。每次使用新输出目录，不覆盖旧结果。`--max-photos 400` 是每机稀疏照片保留上限，不改变 UE 渲染或推理频率；额外关键帧记录有独立预算。可将 `--duration` 改为 60 做接入检查，但短回合不能替代完整正式评分。如需 v22 对照，将提交路径替换为 `artifacts/submission/score-v22/agent.py`，并另用新输出目录；不要同时运行两场比赛。

**保留 `--enable-reports`**：冻结包直接被 SDK 构造时默认开启有门限的上报，但本地 `vision_runner.py` 会用该命令行开关覆盖设置；省略时会关闭上报。`--submission` 使用导出包内的代码及同目录 `vision.pt`，不会自动执行你刚修改的 `src/`。

| 本次运行文件 | 查看什么 |
| --- | --- |
| `run.json` | 启停、退出状态、实际仿真结束时间与耗时 |
| `runner-call.json` | 实际参数、代码和权重哈希、感知模式 |
| `recording.json` | 三机推理、报告及其他控制统计 |
| `observations/<uid>/` | 回合结束后导出的本机公开输入、照片及动作 |
| `official/*.evaluation.json` | 最终总分、清除、报告、惩罚、RMSE及时间线 |

先看最终官方 JSON，运行中 9.47 分后降到 9.06 的情况已经发生过。`OBSERVE`、回放报告数和 mAP 不等于官方捕获或成绩。

## 4. 修改源码后重新导出

当前为局部 CNN、几何定位和解析固定翼规划；v31 新增近圈圆弧终点与匹配曲率转率，不启用 Nano 或 YOPO 学习评分头。“三机搜索、双机接应”策略使用 `--cooperative-capture`，方法与本轮改动见 [COOPERATIVE_CAPTURE.md](COOPERATIVE_CAPTURE.md)。已有的 `--distributed-search` 只选择原搜索策略，不能替代该开关。

以下保留 appearance-v3 权重，导出当前源码到新包。显式指定冻结 v22 `agent.py` 作为 `--controller` 的函数来源，明确导出依赖。导出器会提取其中 `_policy_weights`；当前协同分支选择解析规划，未启用这些学习权重。不能覆盖冻结 v31、历史 v26 或 v22 包。重新导出产生的是新候选，不自动继承冻结包哈希或成绩。

```powershell
$exportDir = "artifacts/submission/dev-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\vision.cmd export `
  --controller artifacts/submission/score-v22/agent.py `
  --weights artifacts/submission/capture-v31/vision.pt `
  --patch-appearance --geometry estimated --cooperative-capture `
  --reports-default-on --output $exportDir
```

然后对 `$exportDir/agent.py` 做相关检查，运行时将 `--submission` 替换为这个路径。`--patch-appearance` 必须保留，当前权重是局部分类器的 state_dict；不能当 YOLO 权重加载。导出生成 `agent.py`、`vision.pt`、依赖、技术说明和 manifest；当前 cooperative-capture 分支的技术说明由 `docs/COOPERATIVE_CAPTURE.md` 复制，正式提交前应检查它是否准确描述你的新版本。

## 5. 重新训练局部外观模型

完成 Git LFS 下载后，按[资产清单的数据迁移步骤](ARTIFACT_HANDOFF.md#训练数据路径迁移)生成本机 `accepted-local.jsonl`。不要使用未经人工审核的候选或裁判真值作为身份标签。

```powershell
$modelDir = "artifacts/vision/models/appearance-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/train_vehicle_appearance.py `
  --reviewed artifacts/vision/datasets/appearance-data-v3/accepted-local.jsonl `
  --output $modelDir --steps 2400
if ($LASTEXITCODE -ne 0) { throw '训练失败，勿继续导出' }

$exportDir = "artifacts/submission/retrained-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\vision.cmd export `
  --controller artifacts/submission/score-v22/agent.py `
  --weights "$modelDir/appearance.pt" `
  --patch-appearance --geometry estimated --cooperative-capture `
  --reports-default-on --output $exportDir
```

此训练命令只读取审核图片并训练局部 CNN，不启动 UE 或比赛。默认不启用额外的 `--appearance-jitter` 实验，其他训练参数见脚本和 `training.json`。重训权重不继承 v31 的 28.33 分、历史 v26 的 18.67 分或 v22 的 9.06 分，须独立检查和正式评测。YOPO 研究源码不属于这条局部外观训练流程，学习评分头未在当前包启用。当前正式 submission 使用 CPU 检测器，`--device cuda` 不会把冻结包自动迁到 GPU。
