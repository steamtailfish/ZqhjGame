# 赛题二：训练、导出与比赛推理命令

当前以首个非零正式分数为优先的实验包、训练和推理命令见 [FIRST_SCORE.md](FIRST_SCORE.md)。下方为仍保留的YOPO式结构化轨迹学习路线；当前score系列使用解析协同搜索，不调用该分数头。

当前版本：`coop-decoy-guidance-v3-51`。适用本机OpenSim2.0.3、红枫2026赛题二、三机独立Agent。以下命令均在**PowerShell**中执行。

本版已接通：真实比赛公开观测采集 → 按回合分离训练/验证 → YOPO式引导学习 → 嵌入权重的单文件Agent → 官方引擎推理。模型控制飞行局部规划，沿用双机候选观察和第三机搜索。

**完成边界：这还不是完整的正式视觉参赛方案。** 当前检测来自官方train模式模拟感知；没有能区分真车/诱饵的已验证视觉权重，相机定位标定/采集位姿对齐也未完成，因此当前不自动上报目标。不要将此文中的“模型训练完成/推理成功”理解为正式视觉验收、K=2清除验收或成绩达标。

## 1. 进入目录

```powershell
Set-Location 'D:\catkin_ws\hf2026-sim-windows'
```

目录约定：

| 路径 | 用途 |
| --- | --- |
| `ZqhjGame/.venv-learning/` | 训练和导出用的独立PyTorch环境 |
| `python/python.exe` | 官方比赛运行解释器；在线推理不需要PyTorch |
| `ZqhjGame/artifacts/datasets/` | 每回合公开规划输入、日志和官方评价 |
| `ZqhjGame/artifacts/models/` | `best.pt`、`last.pt`、指标与训练记录 |
| `ZqhjGame/artifacts/submission/` | 内嵌网络权重的单文件Agent和导出清单 |

`run.cmd --output artifacts/...`相对ZqhjGame目录。`learn.cmd train/export`的文件路径相对当前PowerShell目录，所以下文使用`ZqhjGame/artifacts/...`。输出目录/文件均拒绝覆盖；重跑时换一个实验名。

## 2. 安装学习环境（新机器执行一次）

本机已经建好环境并完成训练验证，不必重复安装。

```powershell
python -m venv ZqhjGame/.venv-learning
.\ZqhjGame\.venv-learning\Scripts\python.exe -m pip install -r ZqhjGame/requirements-learning.txt
```

本机验证环境：Python3.13.9、PyTorch2.7.1+cpu。学习依赖安装在项目内，不修改官方Python或系统包。该依赖文件安装CPU版本；本机下文统一`--device cpu`。CLI支持`--device auto/cuda`，但只有另行配置兼容CUDA的学习环境后才可使用GPU；CPU发行包不能通过一个参数变成CUDA版。

当前工具不调用NumPy。PyTorch可能提示“Failed to initialize NumPy”；这表示NumPy桥接不可用，本版Tensor训练和推理验证已在该环境实际通过。

## 3. 先检查基础代码和梯度链

```powershell
.\ZqhjGame\run.cmd test
.\ZqhjGame\run.cmd check
.\ZqhjGame\learn.cmd verify --steps 2
```

- `test`：原有在线控制/通信/定位合成回归，不启动引擎。
- `check`：官方SDK加载、三实例生命周期与评分合同合成探针，不是实际成绩。
- `verify`：16项学习及部署适配测试，加短合成优化。包括有限差分梯度核对、分数标签梯度隔离、机体系/边界变换、PyTorch与标准库网络数值一致、训练与推理运动模型一致，以及不安全候选回退。

`verify`的合成smoke权重不是部署checkpoint。训练正式版本请使用下一节的真实公开观测数据和`learn.cmd train`。

## 4. 采集真实引擎公开观测

先用两个独立短回合验证通路：

```powershell
.\ZqhjGame\run.cmd collect --duration 20 --seed 71 --redis-port 6395 --output artifacts/datasets/my-v3/train71
.\ZqhjGame\run.cmd collect --duration 20 --seed 72 --redis-port 6395 --output artifacts/datasets/my-v3/val72
```

执行完整600秒采样时，分别改为：

```powershell
.\ZqhjGame\run.cmd collect --duration 600 --seed 71 --redis-port 6395 --output artifacts/datasets/full-v3/train71
.\ZqhjGame\run.cmd collect --duration 600 --seed 72 --redis-port 6395 --output artifacts/datasets/full-v3/val72
```

这些命令启动真实引擎，每次单独管理自己创建的Redis，不修改官方原始场景；必要时只在产物目录生成改变连接端口的场景副本。短回合的20秒不能替代600秒完整回合。

每次输出包括：

- `public-planning.jsonl`：每架机在规划时真正使用的本机公开数据和收到的队友广播，含特征合同版本、回合UUID、仿真时间与来源。
- `collection.json`：采集数、每机最终状态，以及采用网络/回退解析的计数。
- `official/*.evaluation.json`：未改动的官方评价输出。
- `run.json`、`console.log`、`engine.stderr.log`：命令、源码哈希、模式、耗时和异常证据。

Agent回调只将自身记录暂存在实例内，**回合结束后才写文件**。没有从Redis、地图、路线或裁判读取目标真值生成训练标签。记录中的UID/episode_id仅用于数据审计与防泄漏，不进入网络。

训练/验证必须使用不同完整回合。不能把同一回合按帧随机拆分，也不能把同一回合的两架机当成独立训练/验证集；加载器会拒绝重叠episode_id或重复文件。

## 5. 训练局部规划模型

用第4节的短回合数据验证训练命令：

```powershell
.\ZqhjGame\learn.cmd train --train-data ZqhjGame/artifacts/datasets/my-v3/train71/public-planning.jsonl --val-data ZqhjGame/artifacts/datasets/my-v3/val72/public-planning.jsonl --epochs 20 --batch-size 32 --lr 0.001 --device cpu --seed 23 --output ZqhjGame/artifacts/models/my-v3
```

长回合数据的训练示例：

```powershell
.\ZqhjGame\learn.cmd train --train-data ZqhjGame/artifacts/datasets/full-v3/train71/public-planning.jsonl --val-data ZqhjGame/artifacts/datasets/full-v3/val72/public-planning.jsonl --epochs 100 --batch-size 64 --lr 0.001 --device cpu --seed 23 --output ZqhjGame/artifacts/models/full-v3
```

`--train-data`与`--val-data`均支持多个JSONL路径，路径间以空格分隔；含空格路径需加双引号。更多场景覆盖需要采集更多独立回合，而不是只增加epoch。固定seed并不能固定本发行版的全部感知噪声和诱饵路线。

训练输出：

| 文件 | 含义 |
| --- | --- |
| `best.pt` | 按验证集`selected_cost`最低保存的checkpoint；通常用于导出 |
| `last.pt` | 最后一个完整epoch；用于续训 |
| `metrics.jsonl` | 逐epoch训练损失和验证指标 |
| `training.json` | 参数、数据哈希、回合分离、源码哈希、训练前后指标、状态和耗时 |

代价越低越好；`selected_cost`是按网络分数挑出的候选的解析代价，`oracle_candidate_cost`是网络产生的候选中解析代价最低值。两者都来自公开几何，不是裁判得分，也不是目标真值。验证代价暂不执行在线连续安全检查，部署时仍需安全筛选。

模型版本51维：速度、临时目标、观察圆、最多2机通信状态、最多4个公开障碍，加旋转到机体系的4条任务边界半平面与有效掩码。输入/输出定义见`src/zqhj_features.py`；旧v0.2的35维合成权重会被拒绝。

## 6. 断点续训

```powershell
.\ZqhjGame\learn.cmd train --train-data ZqhjGame/artifacts/datasets/my-v3/train71/public-planning.jsonl --val-data ZqhjGame/artifacts/datasets/my-v3/val72/public-planning.jsonl --resume ZqhjGame/artifacts/models/my-v3/last.pt --epochs 20 --batch-size 32 --device cpu --output ZqhjGame/artifacts/models/my-v3-resumed
```

`--epochs 20`表示再训练20个epoch。恢复模型、Adam状态、学习率和打乱样本顺序的随机状态；`--lr`仅用于新训练，续训采用checkpoint的优化器设置。数据文件及其路径/哈希必须与checkpoint一致。输出必须使用新目录，不覆盖旧实验。尚未完成的epoch不会被当作可恢复的完整epoch。

## 7. 导出单文件Agent

```powershell
.\ZqhjGame\learn.cmd export --checkpoint ZqhjGame/artifacts/models/my-v3/best.pt --output ZqhjGame/artifacts/submission/my-v3.py
```

导出同时生成`my-v3.manifest.json`，记录checkpoint哈希、代码哈希和特征版本。

生成的`.py`文件包含网络参数、标准库实现的前向计算、规划器、通信协议与官方`CoopAgent`子类。每架机在自己的实例里初始化权重和运行状态，不依赖其他Agent对象；`sensor/decide`不读权重文件。线上依赖只有Python标准库和官方SDK。checkpoint只在离线导出时用`weights_only=True`加载。

目前该单文件是**控制模块导出**，其中没有真车/诱饵视觉识别模型。不能把文件可加载等同于正式赛事提交内容已全部完成。

## 8. 检查导出文件与运行推理

独立导入检查：

```powershell
.\python\python.exe -B -X utf8 ZqhjGame/tools/check_submission.py --submission ZqhjGame/artifacts/submission/my-v3.py --output ZqhjGame/artifacts/checks/my-v3-isolated.json
```

该检查不加入项目`src/`到导入路径，验证三实例configure/reset、合法有限命令、广播字节数和实例隔离，并要求没有导入PyTorch。

官方dry-run：

```powershell
.\ZqhjGame\run.cmd dry-run --submission ZqhjGame/artifacts/submission/my-v3.py --redis-port 6395
```

真实引擎短时推理：

```powershell
.\ZqhjGame\run.cmd agent --submission ZqhjGame/artifacts/submission/my-v3.py --duration 60 --seed 73 --redis-port 6395
```

完整600秒推理：

```powershell
.\ZqhjGame\run.cmd agent --submission ZqhjGame/artifacts/submission/my-v3.py --duration 600 --seed 73 --redis-port 6395
```

这里“推理”指神经网络不更新参数，只前向预测。**官方CLI仍使用`--mode train`，因为这个mode控制的是感知来源，不是我们神经网络的训练/推理开关。** 本命令不会启动梯度训练，也不会启动UE；采用官方模拟检测。不要直接把它改成eval就宣称正式视觉模式可用，当前SDK默认YOLO首机绑定问题仍在。

需要同时记录网络采用/回退统计时，使用同一模型的记录式推理：

```powershell
.\ZqhjGame\run.cmd collect --submission ZqhjGame/artifacts/submission/my-v3.py --duration 60 --seed 73 --redis-port 6395 --output artifacts/runs/my-v3-neural73
```

查看`collection.json`中每机`diagnostics.neural_selected`、`neural_fallback`和`planner_source`。此命令仍只做推理，回合后额外导出公开规划数据，之后可用于下一轮数据集扩充。不要把测试回合的数据再混入原实验的验证/测试统计。

## 9. 在线执行与赛题规则的对应

- 三架独立Agent，队友状态仅来自合法广播；41字节、2Hz，低于50字节/4Hz限制。
- 按公开相对仿真时间处理TTL、重复帧与控制频率，不累计runner固定dt充当仿真时间。
- 双机候选观察、第三机搜索；候选超时不推断目标已清除，移动也不判为真车。
- 网络输出转率与加速度，约束30度/s、5m/s²、15–40m/s；不发送改变比赛固定高度的命令。
- 云台与FOV继续使用公开接口，FOV为50度；相机定位条件假设不因此变成标定证据。
- 网络分数最高的候选必须通过全部公开障碍、任务边界和机间距检查；网络只编码最近的4个障碍，但安全检查不截断障碍数量。
- 使用完整路径段的最近距离检查和陈旧通信余量；无可行神经候选或输入/输出异常时回退解析规划器，保留计数。两种规划器都不可行时仍显式记录不可行，不能保证未知动态环境绝对安全。
- 上报器已有限频与唯一发布者门限，但缺少可靠真假识别证据，当前不会发出report_target。该缺口直接影响精度得分，不能隐藏。

## 10. 本机已执行的实例

不想重采样时，可直接使用本轮已经生成的文件：

```powershell
# 用已经训练并导出的模型运行推理
.\ZqhjGame\run.cmd agent --submission ZqhjGame/artifacts/submission/competition-guidance-v3.py --duration 60 --seed 64 --redis-port 6395

# 用已有真实公开观测重新训练，使用新输出目录
.\ZqhjGame\learn.cmd train --train-data ZqhjGame/artifacts/datasets/competition-adapt/train61/public-planning.jsonl --val-data ZqhjGame/artifacts/datasets/competition-adapt/val62/public-planning.jsonl --epochs 20 --batch-size 32 --device cpu --output ZqhjGame/artifacts/models/my-retrain-v3
```

本轮train61/val62各20秒，各114条规划记录；完成20epoch训练并单独验证了续训命令。主模型、导出文件、测试与引擎证据见`STATUS.md`。这些数据量只用于打通比赛接口和训练/部署闭环，不能支撑模型已充分训练、跨场景泛化或正式成绩达标的结论。

## 11. 三机 RGB 增量与剩余验收

已在本目录实现 `vision.cmd init/scan/dataset/train/run/verify/fixture/export`。64张已审核的受控公开RGB裁剪完成30epoch双类视觉训练，并接入每机独立推理、条带搜索、实验性地理估计和有条件上报。最新完整视觉Agent包与训练、采集、审核、推理命令见 [VISION_TRAINING_AND_INFERENCE.md](VISION_TRAINING_AND_INFERENCE.md)。本文件前面的v0.3命令仍是历史控制模块链路，使用模拟感知，不会自动切换到最新视觉包。

已完成一次旧单类版本的600秒正式场景运行，0分、0/3；不能替代最新包的性能验证。视觉训练/验证回合复用了布景，不能证明泛化；采集位姿合同、定位绝对误差和真实K=2仍未达标。详细事实与失败记录见 [本轮验收](docs/VISUAL_CLOSED_LOOP.md)，不能以测试通过或权重存在宣称比赛完成。
