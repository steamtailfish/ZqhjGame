# 视觉与引导控制：训练、推理、提交命令

**当前首个非零正式分数路线与新命令见 [FIRST_SCORE.md](FIRST_SCORE.md)。当前score系列采用局部外观分类、图像运动关联、异步视觉和解析协同搜索；以下visual-v9章节为历史记录。**

工程为 `D:\catkin_ws\hf2026-sim-windows\ZqhjGame`。以下 PowerShell 命令从其父目录执行；所有自研内容保存在工程内，官方 SDK、原场景和评分只读。

当前已实际训练双类视觉模型，接通条带搜索、像素跟踪、可选地理估计、协同与有条件上报，并导出完整视觉/控制包。**比赛成绩仍未达标**。旧单类视觉完成了600秒正式场景回合，但为0分、0/3；不能作为最新双类包的验收。最新visual-v9也完成600秒真实回合：0分、0/3、0报告，2次机间距离事件导致4分惩罚，尚未形成K=2。详细证据见 [本轮验收](docs/VISUAL_CLOSED_LOOP.md)。

YOPO引导学习负责候选轨迹代价反传与分数头训练，Gou势场思想提供协同引导；视觉检测使用YOLOv8。YOPO与YOLO不同，本项目没有声称复现深度图四旋翼YOPO全套算法。控制训练见 [控制命令](TRAINING_AND_INFERENCE.md)。

本方案是检测/定位/控制分开训练的模块化基线，轨迹代价尚未反传到视觉编码器，**不是图像到轨迹的端到端YOPO**。mAP仅为检测支路指标，解释见[YOPO范围说明](docs/YOPO_SCOPE.md)。

## 1. 直接运行现有训练产物

最新包为 `artifacts/submission/visual-v9/`，包含自包含 `agent.py`、真实视觉权重 `vision.pt`、依赖 `requirements.txt`、技术报告 `technical_report.md` 和哈希 `manifest.json`。原视觉训练权重为 `artifacts/vision/models/identity-refine-v2/fit/weights/best.pt`；控制权重来自 `competition-guidance-v3`。

```powershell
Set-Location D:\catkin_ws\hf2026-sim-windows

# 最新视觉提交包；输出自动创建时间戳目录
.\ZqhjGame\vision.cmd run --ue-direct --submission ZqhjGame/artifacts/submission/visual-v9/agent.py --duration 60 --seed 90

# 最新包600秒命令；不是已取得成绩的声明
.\ZqhjGame\vision.cmd run --ue-direct --submission ZqhjGame/artifacts/submission/visual-v9/agent.py --duration 600 --seed 91 --max-photos 300

# 开发模式，使用项目源码与指定的两个模型
.\ZqhjGame\vision.cmd run --ue-direct --duration 60 --seed 92 --controller ZqhjGame/artifacts/submission/competition-guidance-v3.py --weights ZqhjGame/artifacts/vision/models/identity-bootstrap-v1/fit/weights/best.pt --geometry estimated

# 显式开启实验性上报，仍须满足全部身份/时间/位置/负责人门限
.\ZqhjGame\vision.cmd run --ue-direct --submission ZqhjGame/artifacts/submission/visual-v9/agent.py --duration 60 --seed 93 --enable-reports
```

包不依赖 `src/zqhj_*.py`，但需要官方SDK和视觉依赖。不要用没有Torch的官方Python加载视觉包。`--submission`使用包内`vision.pt`及CPU/1024/0.25检测配置，忽略开发模式的`--weights/--controller/--image-size/--confidence/--device`；需要这些自定义项时使用开发模式。包默认开启实验性几何、关闭上报；可用`--geometry off`禁用几何。

`--ue-direct`启动已验证可工作的Shipping程序；6379占用时入口失败，只清理自己启动的进程。`--output`必须为工程内新目录；vision/learn的路径相对当前工作目录，旧`run.cmd --output`相对ZqhjGame。

## 2. 安装（本机已完成）

```powershell
python -m venv .\ZqhjGame\.venv-learning
.\ZqhjGame\.venv-learning\Scripts\python.exe -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
.\ZqhjGame\.venv-learning\Scripts\python.exe -m pip install -r .\ZqhjGame\requirements-vision.txt
.\ZqhjGame\vision.cmd init
```

本机验证Python3.13.9、Torch2.7.1+cpu、Ultralytics8.4.77。init核验并复制发行包原模型，保持原文件不变。配置在工程内，禁止自动安装依赖；这不是训练绝对禁网的保证。模型在每机初始化时独立加载，在线sensor/decide仅用本机公开照片、位姿、briefing和合法通信，不读目录/Redis/隐藏路线/其他Agent。

## 3. 已实际完成的视觉训练及复跑

64张256×256车辆裁剪图已人工核对：训练30张、验证34张，两边均有真车/诱饵。审核记录：`artifacts/vision/datasets/fixture-crops-v1/accepted.jsonl`，四张完整审核图册位于同目录。先在自身公开完整照片中确认车辆，再通过特征匹配传播候选框，逐张检查；类别来源为离线受控对象类别，不是裁判输出或模型自动标签。

**四回合复用了相同布景、视角和布局。虽然按回合隔离且无重复图像哈希，仍有高度相似样本；这是训练机制验证，不能证明跨场景泛化。**

```powershell
# 用现有审核数据重建；新目录防止覆盖已完成结果
.\ZqhjGame\vision.cmd dataset --task identity --reviewed ZqhjGame/artifacts/vision/datasets/fixture-crops-v1/accepted.jsonl --val-episode true-height200 --val-episode decoy-height200 --output ZqhjGame/artifacts/vision/datasets/identity-rebuild

# 首轮实际执行参数；这里只把输出改为新的可复跑目录
.\ZqhjGame\vision.cmd train --data ZqhjGame/artifacts/vision/datasets/identity-rebuild/data.yaml --weights ZqhjGame/artifacts/vision/weights/base_vehicle.pt --epochs 30 --batch 8 --size 256 --device cpu --freeze 10 --lr 0.001 --output ZqhjGame/artifacts/vision/models/identity-rebuild

# 导出完整Agent与模型资产
.\ZqhjGame\vision.cmd export --weights ZqhjGame/artifacts/vision/models/identity-rebuild/fit/weights/best.pt --geometry estimated --output ZqhjGame/artifacts/submission/visual-rebuild
```

原始结果位于`identity-bootstrap-v1`，已完成30epochs，最佳模型验证mAP50=0.715、mAP50–95=0.371；真车AP50=0.890，诱饵=0.540。256裁剪保持车辆原像素尺度，完整图推理输入1024。AdamW、workers=0、AMP关闭；training.json、fit/args.yaml、fit/results.csv和best/last权重保存实验信息。训练前验证准备数据/标签哈希。

也已执行小规模解冻微调，结果位于`artifacts/vision/models/identity-refine-v2/`。这是新优化器微调，不是恢复优化器状态；相同受控验证集mAP50=0.982仍不构成泛化证明。复跑命令使用新输出目录：

```powershell
.\ZqhjGame\vision.cmd train --data ZqhjGame/artifacts/vision/datasets/identity-bootstrap-v1/data.yaml --weights ZqhjGame/artifacts/vision/models/identity-bootstrap-v1/fit/weights/best.pt --epochs 60 --batch 8 --size 256 --device cpu --freeze 0 --lr 0.0003 --output ZqhjGame/artifacts/vision/models/identity-refine-rebuild
```

## 4. 采集与标注

```powershell
# 正式场景公开照片，回合结束才写盘
.\ZqhjGame\vision.cmd run --ue-direct --duration 600 --seed 94 --max-photos 300

# 受控训练采集，只改工程内副本；其成绩不能当作比赛成绩
.\ZqhjGame\vision.cmd fixture --ue-direct --duration 26 --fixture-kind true --output ZqhjGame/artifacts/vision/fixtures/my-true
.\ZqhjGame\vision.cmd fixture --ue-direct --duration 26 --fixture-kind decoy --output ZqhjGame/artifacts/vision/fixtures/my-decoy

# 生成待审核框，不自动生成训练真值
.\ZqhjGame\vision.cmd scan --source ZqhjGame/artifacts/vision/fixtures/true-v2 ZqhjGame/artifacts/vision/fixtures/decoy-v1 --weights ZqhjGame/artifacts/vision/models/identity-bootstrap-v1/fit/weights/best.pt --size 1024 --output ZqhjGame/artifacts/vision/scans/my-review
```

`--max-photos`每机0–500，按请求时长分布暂存，不限制推理；不是无偏采样保证。框与原图须按`boxes_photo_sha256`关联。缺失/重复图不累计确认，1秒后停止旧框伺服；该时间限制不证明真实采集延迟。

审核JSONL保持id/episode/uid/image/sha256/source，填写review_status=accepted、真实reviewer及review_evidence；boxes为原图xyxy坐标，category为true_vehicle/decoy_vehicle。单类候选任务用vehicle_candidate和`dataset --task candidates`。核对整图才可标空框负样本。未知身份不伪造标签。后续必须扩展不同布景、视角、距离与遮挡，保留未见场景验证；换episode名不能消除相似数据问题。

`tools/build_fixture_crops.py`为本次固定锚点实验留档，默认输出已存在，会拒绝覆盖；其中像素锚点不能套到新图上。

## 5. 几何、协同和上报边界

实验性`--geometry estimated`从自身光流和自身运动拟合局部平面，检查姿态稳定、纹理、残差与高度离散度。输出明确为own_rgb_motion_plane_estimate、capture_verified=False；工程误差预算不是标定协方差。假设的1秒采集延迟上界未由平台确认，严格采集姿态投影API仍独立保留。

双类置信度≥0.9且类别分差≥0.6才累计身份；至少8个新样本、真车连续一致、定位预算≤80m、照片/估计/轨迹新鲜且对应、本人是OBSERVE队形唯一负责人，才最多1Hz上报。单类不能开启上报。置信度门限不等于已验证准确率。

网络候选检查全部公开几何的路径段距离，并与解析引导的目标/平滑代价比较，拒绝评分头错误偏好的持续绕圈。这增加了解析检查开销，不是纯一步网络性能复现。旧competition-guidance-v3.py作为历史独立控制模块保持不变；最新视觉开发入口和visual-v9已包含质量检查。visual-v9使用fly_to将自身规划方向变为前方300m导航点（零盘旋半径），已在真实回合产生稳定平面估计；实际导航动态仍是近似，不能声称预测轨迹为严格执行保证。

## 6. 检查及结果文件

```powershell
.\ZqhjGame\run.cmd test
.\ZqhjGame\learn.cmd verify
.\ZqhjGame\vision.cmd verify
.\ZqhjGame\.venv-learning\Scripts\python.exe -B -X utf8 ZqhjGame/learning/test_visual_geometry.py
.\ZqhjGame\.venv-learning\Scripts\python.exe -B -I ZqhjGame/tools/check_visual_package.py ZqhjGame/artifacts/submission/visual-v9/agent.py --output ZqhjGame/artifacts/checks/my-visual-package.json
```

| 输出 | 说明 |
| --- | --- |
| run.json | 时长、实际官方时间线、退出与自有进程清理 |
| runner-call.json | 源码/模型哈希、实际包与官方调用参数 |
| recording.json | 三机检测、伺服、网络/回退、报告次数 |
| observations/<uid>/ | 本机公开输入、图像字节/哈希、框和动作 |
| official/*.evaluation.json | 正式场景原始评分，不能以训练损失替代 |
| fixture-evaluation-unused/ | 受控采集评分，不可用于比赛达标声明 |

评分时间线不足请求时长减1秒则入口判失败；不把runner退出0当完整回合。自定义sensor始终抑制SDK默认模拟检测，异常也不回退。已通过项目和仍未完成的K=2等验收见 [VISUAL_CLOSED_LOOP](docs/VISUAL_CLOSED_LOOP.md)。

比赛手册要求不少于2000字技术报告；本轮报告超过2000个汉字，位于[TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md)，已复制到visual-v9包。报告明确区分模块化基线与尚未实现的视觉端到端主线。
