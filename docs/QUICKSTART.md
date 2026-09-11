# 安装、运行、训练与复现

适用 score-v22。**本页所有命令均在 `ZqhjGame` 仓库根目录的 PowerShell 中执行**，不是官方发行包根目录。以下复测使用 seed104，仅作命令示例；已记录的 9.06 分来自 seed101。

## 1. 首次准备

先单独准备已审计的 OpenSim 2.0.3 Windows UE 发行包，将本仓库放在其中，确保 `../competition/`、`../python/python.exe`、`../ue-renderer/`、`../opensim-sim.exe` 存在。官方环境不在本 Git 仓库内，不要把 SDK、UE 或虚拟环境复制进 Git。

在官方发行包目录下首次克隆（已有仓库就跳过）：

```powershell
git lfs install
git clone https://github.com/steamtailfish/ZqhjGame.git ZqhjGame
Set-Location ZqhjGame
git lfs pull
```

按[资产清单](ARTIFACT_HANDOFF.md)下载 Git LFS 文件，当前包、训练数据和测试照片均已包含。运行现有包不需要训练集，也不需要 `vision.cmd init` 下载/复制旧 YOLO 权重。

新机器使用 Python 3.13 重建项目虚拟环境；开发机验证版本为 3.13.9，CPU Torch 2.7.1。不要拷贝开发机 `.venv-learning`。`py` 需要 Windows Python Launcher；未配置时用本机已安装的 Python 3.13 可执行文件替换第一条命令。

```powershell
py -3.13 -m venv .venv-learning
.\.venv-learning\Scripts\python.exe -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv-learning\Scripts\python.exe -m pip install -r requirements-vision.txt
.\.venv-learning\Scripts\python.exe -m pip check
.\.venv-learning\Scripts\python.exe -c "import sys,torch,cv2,numpy; print(sys.version); print(torch.__version__,cv2.__version__,numpy.__version__)"
```

依赖按现有 `requirements-vision.txt` 安装，包含历史视觉工具需要的 Ultralytics；这不表示 v22 在线使用 YOLO。若依赖源或版本不可用，记录失败，不要悄悄换版本后声称复现原环境。仓库没有完整的传递依赖锁文件。

## 2. 不启动引擎的检查

确认当前工作目录和三个关键资产哈希。完整期望值见[资产清单](ARTIFACT_HANDOFF.md)。

```powershell
git status --short --branch
Get-FileHash artifacts/submission/score-v22/agent.py -Algorithm SHA256
Get-FileHash artifacts/submission/score-v22/vision.pt -Algorithm SHA256
Get-FileHash artifacts/submission/score-v22/baseline_evaluation.json -Algorithm SHA256

.\run.cmd check
.\run.cmd test
.\vision.cmd verify
.\.venv-learning\Scripts\python.exe -B -X utf8 learning/test_score_search.py
.\.venv-learning\Scripts\python.exe -B -X utf8 learning/test_visual_geometry.py
```

`run.cmd` 优先使用 `ZQHJ_PYTHON`，其次本项目 `.venv`，最后发行包 `../python/python.exe`；`vision.cmd` 固定使用 `.venv-learning/Scripts/python.exe`。检查通过只证明对应软件链路，不证明比赛得分。

以下隔离检查依赖的固定真车测试照片已随 Git LFS 提供；缺文件时先执行 `git lfs pull`：

```powershell
$checkPath = "artifacts/checks/v22-isolated-$(Get-Date -Format yyyyMMdd-HHmmss).json"
.\.venv-learning\Scripts\python.exe -B -I tools/check_visual_package.py `
  artifacts/submission/score-v22/agent.py --output $checkPath
```

## 3. 运行冻结 v22 并读取结果

关闭自己此前启动的重复比赛，确认 6379 端口没有被另一场比赛使用。不要全局结束所有 Python / Redis 进程。先运行冻结包再修改算法，便于区分环境问题和策略退化。

```powershell
$runDir = "artifacts/vision/runs/v22-$(Get-Date -Format yyyyMMdd-HHmmss)-seed104"
.\vision.cmd run --ue-direct --duration 600 --seed 104 `
  --submission artifacts/submission/score-v22/agent.py `
  --enable-reports --max-photos 500 --output $runDir
if ($LASTEXITCODE -ne 0) { throw '运行失败，先检查本次 run.json 和日志' }

# 必须等待上面的回合结束；同一 PowerShell 会话保留 $runDir。
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/analyze_score_run.py `
  $runDir --output "$runDir/analysis.json"
Get-ChildItem -LiteralPath "$runDir/official" -Filter '*.evaluation.json' |
  ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }
```

600 秒是仿真时间，不是墙钟耗时。每次使用新输出目录，不覆盖旧结果。`--max-photos 500` 是每机保存照片上限，不是推理帧数上限。可将 `--duration` 改为 60 做接入检查，但短回合不能替代完整正式评分。

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

以下保留 appearance-v3 权重，导出当前源码到新包。显式指定冻结 `agent.py` 作为 `--controller` 的函数来源，明确导出依赖（默认值也已改为当前冻结包）。导出器会提取其中 `_policy_weights`；`--distributed-search` 仍选择解析规划，未启用这些学习权重。

```powershell
$exportDir = "artifacts/submission/dev-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\vision.cmd export `
  --controller artifacts/submission/score-v22/agent.py `
  --weights artifacts/submission/score-v22/vision.pt `
  --patch-appearance --geometry estimated --distributed-search `
  --reports-default-on --output $exportDir
```

然后对 `$exportDir/agent.py` 做相关检查，运行时将 `--submission` 替换为这个路径。`--patch-appearance` 必须保留，当前权重是局部分类器的 state_dict；不能当 YOLO 权重加载。导出生成 `agent.py`、`vision.pt`、依赖、技术说明和 manifest；技术说明由现有 `docs/TECHNICAL_REPORT.md` 复制，正式提交前应检查它是否准确描述你的新版本。

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
  --patch-appearance --geometry estimated --distributed-search `
  --reports-default-on --output $exportDir
```

此命令不启动比赛。默认不启用额外的 `--appearance-jitter` 实验，其他训练参数见脚本和 `training.json`。重训权重不继承 9.06 分，须独立检查和正式评测。YOPO 研究源码不属于这条 v22 外观训练流程，旧研究权重已移出当前资产。
