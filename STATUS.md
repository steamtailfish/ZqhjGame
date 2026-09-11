# 最新状态：首个非零正式分数验证

团队交接入口：[HANDOFF.md](docs/HANDOFF.md)、[从仓库根目录运行](docs/QUICKSTART.md)、[需另行同步的资产](docs/ARTIFACT_HANDOFF.md)、[已知问题](docs/KNOWN_ISSUES.md)。以下先列当前 v22，后续各“历史状态”章节只描述当时版本。

v22已完成正式600秒回合（记录至599.917秒）：**9.06分、2报告、0清除、0惩罚，定位RMSE 11.27米**。已满足用户“先拿到分数”的本轮目标；分数来自坐标精度，三个目标coop_ticks均为0，双机持续捕获仍未实现。三机推理异常和异步丢弃均为0。该版采用appearance-v3、图像运动关联、云台6/3度步幅限制和严格短像素轨迹报告；至少4帧跟踪、最近3帧高置信身份、2次一致定位、工程预算≤110米，并保留速度、时效和1Hz门限。v13/v14/v15/v18/v19/v21正式成绩均为0。增强实验appearance-v4复查更差，未部署；新增v5审核候选未进入训练。最新训练与推理命令见[FIRST_SCORE.md](FIRST_SCORE.md)。当前部署为模块化感知和解析规划，未调用YOPO评分头。停止追加优化，保留此实测包供后续迭代。

# 历史状态：得分优化与实际捕获诊断 v0.6

用户优先级改为正式高分，并要求打开可视化和核对多机持续捕获规则。已完成异步私有视觉、合法45字符通信、协同搜索、背景负样本微调与旧帧云台反馈修复，导出score-v12。最新600秒正式实测结束于599.983秒：**0分、0/3、0报告、0惩罚**。三机各1139次推理无异常，但全程SEARCH，没有建立地理轨迹。仍未达到用户要求的高分。

手册和原始裁判确认：K=2，同一真车20秒，中断≤2秒可回补、>2秒清零；自定义OBSERVE不构成实际锁定。用户授权的外部只读记录约417秒，三机实际真车锁定均为0，只有诱饵或未锁定。已打开180秒回放，85秒处可见两机显示OBSERVE但画面没有共同真车。实际瓶颈在搜索覆盖与真车捕获。训练/推理命令及证据见SCORE_OPTIMIZATION.md；禁止把诊断真值坐标加入在线策略。

下方保留历史版本。

# 历史状态：视觉训练、导航与提交包 v0.5

继续在ZqhjGame完成了64张受控公开图像裁剪的人工审核、30epoch初训及60epoch微调的真车/诱饵双类训练、条带搜索、因果平面估计、有条件上报和独立视觉提交包。最新实验包为artifacts/submission/visual-v9，采用微调权重，600秒真实验证已结束，0分、0/3、4分惩罚；命令见VISION_TRAINING_AND_INFERENCE.md，详细证据及局限见docs/VISUAL_CLOSED_LOOP.md。

真实600秒旧单类回合已完成，0分、0/3。已完成的visual-v8双类包60秒完成，0检测异常、0惩罚，三机平面估计通过17/45/31帧，第三机产生1个地理候选；仍为0分、0/3、0报告，没有完成真实K=2。最新visual-v9的600秒回合也已完成，仍0分、0/3、0报告，并出现2次机间距离事件、4分惩罚；三架真车coop_ticks均为0，未形成K=2。不能把回合正常退出当任务通过。采集时间合同、定位绝对精度和跨场景识别仍未验证。

修复了单独set_heading未产生预期导航响应的问题，视觉入口改用公开fly_to执行规划方向；增加网络实际轨迹质量检查。控制/学习/视觉/几何共68项回归通过，独立三实例包加载和回调禁用文件读取通过。三机最新网络采用31/1/0次、解析回退49/79/80次，不能说网络已充分训练。

训练/验证虽按回合隔离，仍复用同一布景和视角，因此视觉mAP50=0.715仅是小范围训练机制证据。模型权重真实存在，但不能声明比赛识别精度已达标。用户指出端到端与mAP的区别后，已明确当前仅为模块化基线，轨迹代价未反传到视觉编码器；说明见docs/YOPO_SCOPE.md。以下保留历次状态，时间性说法以本段和最新验收文档为准。

---

# 历史状态：三机 RGB 推理接入

已按用户要求继续在本目录实现，所有视觉产物位于 `artifacts/vision/`。新增每机私有图像检测、重复/缺帧处理、限幅像素反馈、审核数据集准备和视觉训练入口，并接入已训练的YOPO式引导控制器。命令见 `VISION_TRAINING_AND_INFERENCE.md`，完整证据见 `docs/VISION_INTEGRATION.md`。无需用户另找工程路径。

56项控制、定位、学习与视觉检查通过；内存前向与上游预测在10张原始图片上数值一致。两个60秒真实RGB回合通过运行验收，均0检测异常、0惩罚，但0分、0/3、0报告。最终seed74三机各83次视觉推理，神经采用78/83/78次、解析回退5/0/5次。中间20秒尝试只运行至评分时间14.3秒，已判为失败并保留；原因尚未定位，没有降低验收门限。

历史450张图片仅出现两个低置信候选，视觉审核均不足以确认车辆，未作为正标签。视觉训练工具已实现，但缺少合格正样本，未执行视觉微调。拍摄姿态对齐、FOV/高程、真假识别、在线地理定位、K=2/600秒验收仍未完成；当前不能称完整赛事适配。原有控制训练权重和单文件导出保持可用。

---

# 历史状态：比赛控制训练/推理链路v0.3

用户要求完全适配比赛并提供训练与推理命令MD。本轮已完成能独立完成的控制部署链路，主文档为`TRAINING_AND_INFERENCE.md`。**整场比赛的视觉识别/定位和成绩验收仍未完成**；已询问真车/诱饵权重或数据及相机标定/采集位姿资料，目前未收到。未将官方train模拟检测冒充正式视觉识别。

新增51维统一机体系特征，包含4条任务边界半平面；训练/推理特征与运动模型、标准库网络与PyTorch前向均通过一致性检查。学习候选经过全部公开几何的路径段间距检查，再输出限幅控制；失败或不可行时回退解析规划器。可导出包含模型权重的单个CoopAgent模块，每个实例拥有各自运行状态，线上无PyTorch和权重文件I/O。

新增`run.cmd collect`、`--submission`、`learn.cmd train/export/verify`；支持按完整回合隔离训练/验证、mini-batch、best/last checkpoint、同数据续训、版本拒绝、数据/模型/源码哈希。采集仅在回合结束后导出实例内公开规划输入，不读取真值生成标签。旧35维smoke模型不能部署。

| 验证层级 | 本轮结果 |
| --- | --- |
| 静态 | 60个官方文件SHA256与原审计一致；SDK、原始场景和裁判未改 |
| 在线合成回归 | 28项通过，artifacts/checks/competition-adapt-tests/ |
| 学习/适配 | 16项通过，artifacts/learning/competition-adapt-contract-tests/ |
| 独立单模块 | 不加入src路径、不导入torch，3实例configure/reset及15条命令检查通过；artifacts/checks/competition-adapt-isolated.json |
| 真实公开数据 | seed61、62分别20秒，各300tick/114条记录/0惩罚；artifacts/datasets/competition-adapt/{train61,val62}/ |
| 训练 | 20epoch；验证selected_cost从3.889185降至最后epoch的2.850217。best.pt为epoch19，selected_cost=2.793562。均为规划代价，不是赛事得分；artifacts/models/competition-guidance-v3/ |
| 续训 | 从last.pt恢复1个epoch，实际epoch21；artifacts/models/competition-guidance-resume-check/，未覆盖主模型 |
| 导出dry-run | 正常退出，19合成帧；artifacts/checks/competition-adapt-submission-dry/ |
| 真实网络推理 | seed63、60秒train感知、901tick、约121.732墙钟秒、退出0；三机各113次网络控制，0回退、0惩罚；0分、0/3、0报告。artifacts/runs/competition-adapt-neural63/ |
| 600秒/正式视觉/K=2达标 | 本轮未完成，不能声称完全参赛适配或性能达标 |

可运行主导出：`artifacts/submission/competition-guidance-v3.py`及同名manifest。SHA256为6398df00b8d067533951381f15cd0d4237049ae49ab641105a240328d24f1994。这是控制模块封装，不含视觉分类器。正式完整提交仍需视觉、技术报告与完整回归验收。

完整命令、目录语义、感知mode与网络训练/推理区别、输出解释和剩余问题见`TRAINING_AND_INFERENCE.md`。600秒命令已提供，但没有假称已执行。

---

# 历史状态：YOPO引导学习适配v0.2

用户后续提出使用YOPO引导学习。已在`learning/guidance.py`实现35维几何特征→9组有界基元偏移→可微固定翼轨迹→代价反传；分数头以`-J.detach()`单独训练。详见docs/GUIDANCE_LEARNING.md。这次确实进行了小规模网络优化，不能再笼统声称“从未训练”，但没有正式赛事数据训练或完整YOPO深度网络复现。

验证：独立`.venv-learning/`的Python3.13.9、PyTorch2.7.1+cpu环境，8项梯度/隔离/约束测试通过，32个合成训练样本、32个独立合成留出样本、CPU40步更新。留出样本的所有候选平均代价1.872790→1.444640，按网络分数选出的候选代价1.680905→1.298894；仅说明该小规模合成试验成本下降，不是比赛得分或真实安全/泛化证据。

原始证据：artifacts/learning/20260910-guidance-smoke/{run.json,tests.log,synthetic-smoke.pt}。源码哈希、环境依赖、每步损失和梯度、权重哈希均有记录。所有新增代码和依赖环境在ZqhjGame内；默认run.cmd仍选择原比赛解释器。在线EntryAgent及其控制策略未改，没有加载合成权重。本轮未启动引擎或UE。

尚缺：真实公开观测到机体系特征的部署适配、真实训练数据/感知距离证据、任务边界与连续安全验证、与解析基线的真实对照。当前RGB photo不能当深度图；完整视觉YOPO及真实K=2仍未完成。

---

# 历史状态：论文启发的自研代码v0.1（2026-09-10）

用户要求直接参考Gou围捕控制与YOPO两篇论文构建代码。本轮已将EntryAgent从空动作壳改为解析协同控制入口，新增合法时间/含噪短轨迹、41字节2Hz广播、双机候选仲裁、APF引导及固定翼局部轨迹筛选。第三机保守搜索，候选观察尝试有时限；不推断哪个目标已清除。实现对应与限制见docs/PAPER_GUIDED_IMPLEMENTATION.md，使用说明见README.md。

没有训练网络或复制YOPO仓库；没有把本版称为论文算法复现。EntryAgent使用公开SDK检测作为未核实候选，不把运动/置信度当真假判据，不发report_target。VisualEntryAgent禁止默认检测器回退，但尚无在线检测器；原photo投影的采集位姿拒绝机制保留。D在线视觉定位、真实K=2与完整成绩尚未验收。

| 验证层级 | 本轮结果与原始证据（项目内路径） |
| --- | --- |
| 静态 | 8个在线模块语法通过；结束时60个官方文件SHA256与原审计一致。artifacts/checks/20260910-guided-agent-static.json、20260910-guided-agent-final.json |
| 官方导入/合同 | 三实例configure/reset及SDK合同通过。artifacts/checks/20260910-guided-agent-contract/ |
| 合成测试 | 28项通过，包含原13项定位测试及新增15项时间/轨迹/协议/控制/协同回归；两机通过模拟广播收敛不等于真实K=2。artifacts/checks/20260910-guided-agent-tests/ |
| dry-run | 自研入口2秒、19合成帧，正常退出；无真实目标。artifacts/checks/20260910-guided-agent-dry/ |
| 真实引擎短回合 | seed42、8秒、train模拟感知、3实例；末计分时间7.9333秒、120tick，退出0，约24.438墙钟秒；无decide异常，0分、0/3、0报告、0惩罚。artifacts/runs/20260910-guided-agent-engine-smoke/official/coop_decoy_1789032305.evaluation.json |
| 真实完整回合 / UE视觉 / 训练 | 本轮均未执行，不报告效果提升或完整回合成绩 |

新增run.cmd test模式（不启动Redis/引擎），运行记录包含自研源码哈希。开发与产物均位于ZqhjGame/；未修改官方SDK、场景、评分或原有YOPO/目录，未安装新依赖。结束检查6395无监听、无opensim-sim.exe进程。原有字节码缓存修改和用户文件保留。

后续先接通有来源和采集姿态证据的视觉候选，再验收真实双机共同观察；学习网络、目标真假识别、上报交接、单模块导出和完整回归继续按计划推进。

---

# 历史状态：官方基线多回合评测（2026-09-10，用户要求停止）

用户本轮授权充分运行官方基线采分。预先固定12个完整600秒回合：seed42–51各一次，seed42再重复两次；4路独立Redis/引擎/输出。使用原CoopDistributedAgent、train模拟感知及官方默认参数，无UE/YOLO、训练或调参。不能冒称正式视觉验证赛结果。

接口检查通过：artifacts/checks/20260910-batch-contract。开始前60个官方文件与原审计SHA256全部一致。已有Python字节码缓存修改、YOPO/和旧可视化output/均保留未清理。原项目规划不改。

运行证据：artifacts/baseline-batch/20260910-12rounds/batch.json及各回合run.json、official/*.evaluation.json、console.log、engine.stderr.log、redis/。汇总入口tools/summarize_baseline_batch.py输出scores.csv、summary.json、REPORT.md，进行中报告仅列已验证完整回合，不能把中途分数计作最终成绩。

新增tools/run_baseline_batch.py及tools/summarize_baseline_batch.py；另按用户要求新增tools/watch_baseline.cjs并打开人用三维观察界面，连接本批次6391端口，禁用浏览器写命令，未将全态势输入Agent。

用户随后明确要求停止，本次批量评测与配套观察服务已终止。已完成seed42–45共4个完整600秒回合，均通过完整运行核验：全部0分、0/3摧毁，报告659/816/780/625条，总体报告RMSE约739/1009/1424/952米，惩罚0/2/14/15分，双机有效跟踪计数均0。三个评分维度均0。每轮约1133墙钟秒；这些为训练参考结果，不是正式视觉验证成绩。

seed46–49共4轮被用户中途停止，日志保留，不计为完整成绩或基础设施失败；其余4轮未开始。原定12轮未完成，不能声称已完成多种子泛化验证或同种子重复统计。batch-at-stop.json和run-at-stop.json保留停止前状态，stop-processes.json记录仅终止已核验的本批次PID树。停止后60个官方文件SHA256与开始前相同，相关服务端口已无监听。最终部分结果在本批次REPORT.md、summary.json、scores.csv及各轮原始official/*.evaluation.json。

---

# 历史状态：photo到候选位置（2026-09-07）

本轮只推进定位探针，未重写PROJECT_PLAN。完成时间适配、明确来源的候选结构、针孔射线/局部平面投影与拒绝机制。真实42秒采样退出0；13项合成测试通过。详见docs/PIXEL_LOCALIZATION_VALIDATION.md。

官方60文件哈希复核未变，无残留本轮服务；结束时另有用户未跟踪YOPO/目录，未触碰。未安装依赖、未训练、未执行双机协同。

一个本机真实图像角点经离线视觉选点、同图块对应和两帧求解，在留出第三帧重投影差约1.62px；输出带假设的有效位置例约(27.00163858,124.99039416)。这是**离线条件几何通过**，不是在线视觉定位或绝对精度达标。没有在线自动候选；FOV轴/高度存在歧义，采集时刻和对应姿态仍未知，暂不具备最小双机目标观察条件。

证据：artifacts/probes/20260907-213142（seed42，42秒，631tick，官方原始输出0分/0惩罚）；artifacts/localization/20260907-geometry/pixel-evidence-final（原图路径/哈希、候选、时间、投影假设、有效与无效案例及标记图）。不把离线标注、拟合高度或位置注入在线代码。

---

# 上轮状态：2026-09-07晚感知/控制验证

用户决策已落实：D前置、A主路线、B后续；没有YOPO移植、训练或批量调参。下文原环境审计保留历史，新结论详见docs/PERCEPTION_CONTROL_VALIDATION.md。

- **通过**：本机真实UE三机公开photo（JPEG 1024×768，180张解码零失败）、基本云台/FOV/导航/速度响应、三种时间区分、广播去重和自消息处理；seed42、60秒真实探针运行退出0。
- **官方原始输出**：artifacts/probes/20260907-204636/official/coop_decoy_1788785330.evaluation.json；901tick，末帧59.9833s，0分、0/3、0报告、0惩罚。不是双机/识别通过。整次含加载与收尾136.618墙钟秒。
- **失败保留**：204458编排NODE_PATH缺失已在项目内修复；204515官方UE bootstrap退出9004；204636使用包内Shipping直接启动成功。send_to每机12次，三机均未收到D消息，未改官方参数绕过。
- **未执行/阻塞**：图像→候选坐标未验证，默认YOLO首机绑定不能证明三机视觉定位；定向投递仍未通过。本轮未做双机共同观察、真假识别或自研600秒回合，不用模拟检测替代真实视觉证据。
- **主办方确认**：正式三机图像/GPU条件与权重附件提交；eval回退/首机绑定、自定义sensor预启动冲突；相机坐标/FOV/时间同步；send_to及滑窗细则。
- **新增文件**：src/zqhj_probe.py；tools/run_perception_probe.py、render_probe_service.cjs、analyze_perception_probe.py；probe.cmd；docs/PERCEPTION_CONTROL_VALIDATION.md。更新AGENTS.md、PROJECT_PLAN.md、ENVIRONMENT_AUDIT.md、SDK_CONTRACT.md及本状态文件。所有原始观测、图片、命令、日志与官方结果在artifacts/probes，回调内无文件I/O。
- **下一步唯一优先功能**：本机photo到单候选位置的最小定位探针，验证像素方向/云台FOV/地面投影与缺帧处理，不先做搜索分配或训练。

---

# 本轮状态

日期：2026-09-07。**环境审计、规划和最小入口完成；官方基线600秒真实引擎回合完成，成绩0/100，未达标。** 无复杂算法、训练或批量调参。

SIM_ROOT：`D:\catkin_ws\hf2026-sim-windows`。
PROJECT_ROOT：`D:\catkin_ws\hf2026-sim-windows\ZqhjGame`（原有工程目录）。

## 完成与已验证

- 已读原Word的全部正文、5表和2嵌图，提取186正文块；原文件未变。没有页面渲染器，未校对分页/版式，不把内容提取说成整页渲染验证。
- 已审查SDK、Windows脚本、实际赛题二基类/观测/命令、官方基线、CLI/加载器/runner/当前裁判、相关配置；范围和源码/手册位置见审计、接口合同。
- 确认为OpenSim2.0.3 Windows UE增强包；用包内Python3.12.13、redis8.1.0、PyYAML6.0.3，未安装新依赖、未改系统Python。
- 实际官方CLI帮助通过；官方基线导入、三实例configure/reset通过；自研单模块合法导入通过。当前自研EntryAgent只返回空动作，未实现搜索或协同。
- 当前SDK合成合同探针通过：三实例隔离、50字节UTF-8边界、观测字段、K=2/20秒、2秒中断、事件式间距惩罚；同时显式复现时间原点缺陷。这些都不是真实引擎成绩。
- 修正工程dry-run对Redis的前置条件后，官方基线与自研入口dry-run通过。只含1个合成UAV、无真实目标，不算基线成绩。
- 官方原CLI真实引擎5秒冒烟通过：3机、18车A*注入全部成功、生成原始评价JSON。
- 固定seed=42，duration=600，官方原基线完整真实回合通过运行验收；原始评分已保存，见下表。
- 官方发行包 `examples._common.tests.score_e2e_smoke` 补充检查通过：真实Redis上6条人工评分消息全部收到。该检查晚于完整回合执行，仅证明发布链路；人工消息中的80分没有真实比赛含义，也没有生成其声称路径的评分文件。
- 从 `D:\catkin_ws` 调用项目入口并显式传入SIM_ROOT通过；中文和空格输出路径通过，官方子进程cwd仍为SIM_ROOT。
- 最终核对60个官方文件哈希无变化，端口场景副本仅更改Redis连接；Git状态仅 `?? ZqhjGame/`。6个自研Python文件语法解析通过；基线日志没有decide异常。证据：`artifacts/final_verification.json`。
- 15:35:41最终服务检查：无opensim-sim.exe/redis-server.exe残留，6379/6380无监听；未停止不相关程序。证据：`artifacts/final_process_state.json`。

## 官方真实完整回合

目录：`artifacts/runs/20260907-150656-014534-baseline-seed42/`。

- 原始官方评分：[coop_decoy_1788765939.evaluation.json](artifacts/runs/20260907-150656-014534-baseline-seed42/official/coop_decoy_1788765939.evaluation.json)
- 完整命令/环境/进程/耗时：[run.json](artifacts/runs/20260907-150656-014534-baseline-seed42/run.json)
- 原始控制台：[console.log](artifacts/runs/20260907-150656-014534-baseline-seed42/console.log)
- 运行中只读诊断：同目录observer-snapshot.json、comm-observations.json；只供离线审计，不允许在线导入。

| 指标 | 原始结果 |
| --- | --- |
| 时间 | 2026-09-07 15:06:56–15:25:39，UTC+8 |
| 基线类 | baselines.coop_distributed:CoopDistributedAgent（官方未改） |
| 模式 | train / photo-mode auto；未启动UE，默认统计识别器 |
| 种子与时长 | seed42，请求600仿真秒；最后计分帧599.9499999997824秒，达到终止边界后正常退出 |
| 评分profile | multi_uav_coop_decoy，K=2，dwell=20s，grace=2s |
| 总分/基础分/惩罚 | 0.0 / 0.0 / 2.0 |
| kill / accuracy / mission_time | 0.0 / 0.0 / 0.0 |
| 清除 | 0/3；passed=false |
| 已接受上报 | 661条（不是所有发出的报告数） |
| 总体诊断RMSE | 645.166189100246m；不能代替逐目标精度评分 |
| 违规计次 | 机间距1次，越界0次 |
| 计分帧 | 9005；与仿真秒/固定dt不能简单等同 |
| 退出码/墙钟 | 官方CLI=0、工程入口=0；1123.534秒（约18分44秒） |
| 场景初始化 | 3个Agent；3真车+15诱饵A*注入ok=18、fail=0 |
| 评分SHA-256 | c51cec8d839ff28fd0fa515898bbf9fa6a175e6fe46816ab2676a81e87096dad |

结果说明：是真实引擎运行的本地train模式官方基线成绩，不是mock/dry-run，也不是UE/YOLO或正式赛事成绩。某目标出现过100个有效协同计分帧、一次跟踪重置，但无目标达到清除条件；另外两个没有协同帧。官方JSON不输出逐目标报告数/RMSE，不能据此报告不存在的分桶明细。基线源码已注明K=2未适配，又假设诱饵静止，因此环境成功运行不意味着算法达标；单次结果也不证明所有种子都会0分。

## 已执行命令与工作目录

除表中注明外，调用及子进程工作目录均为SIM_ROOT，使用包内 `python/python.exe`。每项展开argv、解释器、环境变量、UTC开始时间、退出码、耗时保存在指定目录的command.json或run.json。手册提取另用Codex依赖运行时Python，仅因它是文档工具环境，不用于比赛回合。

| 操作/实际命令 | 结果与记录目录（artifacts下） |
| --- | --- |
| Get-Location、Get-ChildItem；rg --files/rg -n定向定位和行号读取；Get-Content相关文件 | 静态读取，清单见docs/ENVIRONMENT_AUDIT.md；没有遍历UE/第三方资源内容 |
| git status --short；git rev-parse --show-toplevel/HEAD；git log -1；git-lfs版本及选定LFS信息 | 初始干净，最终只新增项目；无reset/clean/init |
| Python版本与redis/yaml导入探测；Get-CimInstance/端口监听读取 | 包内可用、系统Python缺redis；没有处理不相关进程 |
| Codex文档Python运行tools/extract_manual.py读取原Word；view_image打开两个提取图片 | docs/manual完整提取，无原件修改；没有原文页面渲染 |
| powershell.exe -NoProfile -File .\preflight-check.ps1 | **失败1**，0.179s，checks/20260907-150225-466882-preflight；执行策略拒绝，未绕过 |
| .\python\python.exe -B -m competition run --help | **通过0**，0.146s，checks/20260907-150250-981944-cli-help；最初记录器显示中文发生UnicodeEncodeError，子命令已成功、日志已落盘，修复显示编码后用项目help重跑 |
| .\opensim-sim.exe --help | **失败1**，约0.028s，checks/20260907-150250-983353-engine-help；引擎忽略help并尝试缺失config.json，不能称help通过 |
| Python -c导入官方加载器、创建3个基线实例configure/reset | **通过0**，0.553s，checks/20260907-150251-003353-baseline-import；完整代码在command.json |
| .\ZqhjGame\run.cmd help | **通过0**，0.335s，runs/20260907-150505-042398-help-seed42 |
| 首次2秒dry-run（显式--no-start-sim，尚未自动启Redis） | **失败**，144.555s，runs/20260907-150505-625196-dry-run-seed42；ScorePublisher懒连接反复超时、无评分；按唯一命令路径定位并只终止该CLI PID27348，保存退出4294967295 |
| .\ZqhjGame\run.cmd smoke --seed 42 --redis-port 6380 | **真实5秒通过0**，18.865s，runs/20260907-150606-286121-smoke-seed42；official/coop_decoy_1788764785.evaluation.json，0分、0/3、5报告、末帧4.9333s |
| .\ZqhjGame\run.cmd baseline --seed 42 --redis-port 6380 | **真实600秒通过0**，1123.534s，runs/20260907-150656-014534-baseline-seed42；见完整结果 |
| .\ZqhjGame\run.cmd dry-run --seed 42（自动专用Redis） | **dry-run通过0**，3.280s，runs/20260907-150730-649562-dry-run-seed42；19合成帧、0目标 |
| .\ZqhjGame\run.cmd check | **合成合同通过0**，0.737s，runs/20260907-150932-282252-check-seed42 |
| .\ZqhjGame\run.cmd dry-run --seed 42 --agent zqhj_entry:EntryAgent --output "artifacts/runs/入口 中文 空格检查" | **dry-run通过0**，3.272s，runs/入口 中文 空格检查；单模块加载、中文空格路径 |
| Python -B tools/snapshot_environment.py（通过record_command执行） | **通过0**，0.816s，checks/20260907-151151-228688-release-hashes；docs/release_manifest.json |
| 在D:\catkin_ws，用绝对路径调用run.cmd check --sim-root "D:\catkin_ws\hf2026-sim-windows" --output "artifacts/runs/外部目录 显式路径检查" | **通过0**，0.732s；子进程cwd核实为SIM_ROOT |
| .\ZqhjGame\run.cmd score-smoke | **官方Redis消息冒烟通过0**，1.456s，runs/20260907-153224-790146-score-smoke-seed42；未运行引擎 |
| 在D:\catkin_ws，用绝对路径调用run.cmd check --sim-root "D:\catkin_ws\hf2026-sim-windows"（入口最终修改后） | **通过0**，0.732s，runs/20260907-153224-761149-check-seed42；run.json保存launcher_cwd与子进程cwd |
| Python -c最终哈希、端口副本、评分、日志和语法核对（通过record_command执行） | **通过0**，0.686s，checks/20260907-153258-522828-final-verification；完整代码在command.json |

运行中的通信/时间观测通过包内Python只读订阅本轮专用Redis6380，保存汇总文件。没有向Agent提供额外状态，也没有向Redis下发调参/控制命令。初次dry-run失败记录保留，不覆盖或伪装为成功。Redis以本次Popen句柄结束，Windows terminate返回1记录在redis_exit_code，不是CLI失败；完整基线CLI退出码另为0。

## 本轮新增自研文件

| 文件 | 用途 |
| --- | --- |
| AGENTS.md | 修改边界、赛题约束、运行和必读文档索引 |
| docs/ENVIRONMENT_AUDIT.md | 发行版本、文件审查范围、运行链路、环境/复现、证据和冲突 |
| docs/SDK_CONTRACT.md | 真实观测、命令、单位、时间、通信、评分和信息边界 |
| PROJECT_PLAN.md | 分阶段开发、模块边界和验收；保留单模块导出和回归 |
| STATUS.md | 本文件 |
| docs/manual/{MANUAL_EXTRACT.md,body.json,manifest.json,media/*} | 原Word可核验提取与两张原始图片 |
| docs/release_manifest.json | 官方关键文件尺寸/哈希及解释器/依赖版本 |
| run.cmd、tools/run_competition.py | 自定位、覆盖SIM_ROOT、统一导入、专用进程、命令/评分记录 |
| src/zqhj_entry.py | 继承真实CoopAgent的单模块空动作加载壳 |
| tools/check_contract.py | 当前SDK离线合成探针，非比赛成绩 |
| tools/extract_manual.py、record_command.py、snapshot_environment.py | 手册提取、命令证据、版本快照 |
| requirements.txt、.gitignore | 验证依赖、忽略.venv/缓存/本地运行产物 |

运行证据均保存artifacts；该目录被项目.gitignore忽略以免误提交大型/含真值实验产物，文件并未删除，需要共享实验时单独归档。未git add/commit，用户可自行审阅新文件。

## 未执行、限制与当前阻塞

- 未执行安装脚本、全局依赖安装、start.ps1/stop.ps1宽范围清理、verify.ps1前端健康校验；preflight被执行策略阻止，未绕过。必要的引擎与SDK验证已由现有CLI完成，本轮没有尚未完成的真实回合阻塞。
- 未启动前端或UE、未测试三路photo、未跑YOLO eval、未下载模型。UE增强包存在不等于图像通路已通过；底层云台/运动/通信精确限制未全部实验确认。
- 未提供引擎C++和引用的contracts/specs原文，未反编译；手册分页未渲染。正式部署版本、惩罚口径、time原点修正、区域边界、多机视觉与提交加载命令需要主办方确认。
- 无旧项目规划文件可逐项比对；规划依据实际审查重写。没有自研算法真实完整回合成绩。
- 不修改本地裁判消除time缺陷，不通过持久在线违规、读取全局信息或路线记忆利用实现差异。

下一步最优先实现：合法观测的相对仿真时间适配、通信序号/TTL/收件去重和自消息处理；随后做真实云台小实验与最小双机接应/共同跟踪。阶段验收见PROJECT_PLAN.md。
