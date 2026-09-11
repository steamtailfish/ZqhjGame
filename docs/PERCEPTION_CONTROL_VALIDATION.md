# 感知、时间与控制验证（2026-09-07晚）

## 范围与结论

实际SIM_ROOT：`D:\catkin_ws\hf2026-sim-windows`；PROJECT_ROOT：其下已有`ZqhjGame`。发行包OpenSim2.0.3，build 2026-09-03T09:45:29Z。此前完整审计不重复，本轮只追踪感知链路和做一个60秒真实探针。用户选择D感知验证前置、A主路线、B后续局部改进；没有YOPO移植、训练、批量seed或新依赖安装。

**本机三路合法photo已实测可用；正式赛事图像配置和权重提交仍需确认。** 基础控制与广播通过，公开send_to投递未通过，真实图像到候选坐标未完成验证。本轮没有启动双机共同观察，也没有真假识别通过结论。

## 正式条件：文档与源码分开

以下路径相对SIM_ROOT；行号以本次发行包为准。

| 条件 | 核验结论与依据 |
| --- | --- |
| train/eval | SDK-API.md:98–109称eval用于官方评测、train用于本地开发。源码core/runner.py:235–271实际仅在`eval AND yolo_model_path非空`时启动YOLO，其他情况仍是AccuracySimulator。因此单写eval不证明启用图像推理。 |
| UE与photo | UE是渲染服务；`photo_mode != off`且非dry-run才启动PhotoCache。auto/on在这段实现没有强制等待/保证帧的区别，off完全不拉图。train也能有真实photo。模式名不决定是否有图。 |
| 三机归属 | core/runner.py:438每UID建独立Agent，:551附近将`photo_cache.get(uid)`放进该UID的SelfView。core/perception/photo_cache.py:30–85按UID独立线程缓存。本轮在线探针只读取obs.self.photo。 |
| 自定义sensor | core/perception/resolver.py:53–73：非空list采用自研结果；[]明确无检测；SKIP_DETECTION跳过默认检测；None或异常回退默认。算法要显式处理失败，不能误返回None让模拟检测悄悄进入。 |
| sensor文档冲突 | SDK-API.md:173称自定义sensor时默认识别器不启动；runner.py:260–264却在调用sensor前无条件启动满足eval+model条件的默认YOLO。自定义结果选择和默认worker启动是不同问题，源码优先用于描述本地行为，不代替正式规则。 |
| 默认eval回退 | SDK-API.md:255–263、resolver.py:76–93：本机photo缺失会回退AccuracySimulator。存在图像不保证YOLO成功；其依赖错误也不应当作感知合格。 |
| 默认多机YOLO限制 | runner.py:260绑定uids[0]；SDK-API.md:263明确非首机也可能得到首机的检测。三路photo缓存分别正确不意味着默认三机Detection正确。 |
| 本轮实际模式 | train + photo_mode=on + 自定义sensor返回SKIP_DETECTION。真实UE图像、真实动力学、真实官方裁判；不运行模拟检测或YOLO识别。不是dry-run，也不是完整600秒比赛回合。 |

### 真实图像模式下target_lat/target_lon从哪里来

`core/perception/default_detectors.py:143–195` → `examples/yolotrack/yolotrack/yolo_vision.py:180–223,263–308` → `core/perception/bbox_to_latlon.py:37–72`：

1. YOLO worker读它绑定的单一UAV图像，选择置信度最高的一个框，框中心线性换成pan_delta/tilt_delta。该内部worker的Redis读取属于官方实现；本项目在线Agent不调用它、不直接读Redis。
2. YoloDetector用**当前调用Agent的**位置/高度/云台角加这个检测角，假设目标地面alt=0，将视线交地后换成经纬度。它不是UE直接返回目标世界坐标，也没有用真值补齐。
3. 默认水平/垂直FOV为60/45度；不是从本帧obs.self.gimbal_fov_deg取得。几何工具不接收机头heading；pan按0北90东直接投影，tilt取绝对值。地形起伏、相机内参、姿态与图像同步均未在此闭合；与基线相对机头pan的使用存在风险。
4. 输出一个Detection，无目标ID、bbox、捕获时间戳或跨帧轨迹ID；没有能保证“前后两个位置属于同一个目标”的关联器。非首机可能把首机框角和自身位姿相混合。
5. worker的get_latest(max_age_ms=200)比较墙钟上的最近推理结果更新时间，不是图像捕获时间。_tick读取sim_time但_infer构造结果时填0；不能把200ms当相机延迟保证。

自定义sensor可以自己从**本机photo**输出Detection；这条合法接口已确认，但本轮没有实现或验证视觉候选定位，SKIP探针不产生target_lat/target_lon。不得把train模拟位置当作真实视觉定位已通过。

手册4.5（提取B0129–B0132）只明确单模块Agent、依赖文件、技术报告及可选日志/视频；B0134说验证环境要素不变、目标走新路线、客观评分标准相同。**不能从这些文字推导权重附件许可、加载路径、GPU额度、三机图像分辨率/帧率或允许离线加载大模型。** SDK支持自研模型也不等同最终提交制度明确。

## 可复现运行与原始证据

解释器：`SIM_ROOT/python/python.exe`，Python3.12.13；redis8.1.0、PyYAML6.0.3。Node为`SIM_ROOT/bin/node.exe` v22.11.0；官方lib/node_modules已有ioredis。发行包Python没有PIL/numpy/cv2/torch/ultralytics，本轮不安装。包内`examples/yolotrack/target_vehicle_yolov8s.pt`存在，但没有运行其推理，也不据此认定可提交。

实际主要命令均从SIM_ROOT执行：

```powershell
& .\python\python.exe -B -X utf8 .\ZqhjGame\tools\run_perception_probe.py
& .\python\python.exe -B -X utf8 .\ZqhjGame\tools\run_perception_probe.py
& .\python\python.exe -B -X utf8 .\ZqhjGame\tools\run_perception_probe.py --ue-direct
```

| 记录目录（相对ZqhjGame/artifacts/probes） | 结果 |
| --- | --- |
| 20260907-204458 | 启动器退出1，0.762墙钟秒。自研编排缺NODE_PATH导致官方JS找不到ioredis；在项目入口补入与官方start.ps1相同的NODE_PATH后解决，未安装包。无UE、无引擎、无成绩。 |
| 20260907-204515 | 退出1，27.755墙钟秒。官方UE bootstrap testwl.exe退出9004，stdout空，未注册renderer。9004根因未确认。无引擎、无成绩。 |
| **20260907-204636** | **入口/官方runner退出0，136.618墙钟秒（包含加载与收尾）**。直接启动包内Shipping程序后UE正常注册、三机分配，官方runner完整执行所请求60秒。 |

成功记录：`artifacts/probes/20260907-204636/run.json`存各子进程完整argv、cwd、PID、退出码、种子和耗时；`runner-call.json`存官方公开Python入口及全部参数。引擎和Python cwd为SIM_ROOT；UE cwd为`SIM_ROOT/ue-renderer/Windows`。

实际UE命令（cwd如上）：

```text
testwl/Binaries/Win64/testwl-Win64-Shipping.exe /Env_MultiBS_Data/Maps/Map_MultiBS.Map_MultiBS -windowed -resx=1 -resy=1 -renderoffscreen -nosound -minimalviewport
```

地图和参数来自start.ps1:477–493及config/renderers/ue_testwl.json；唯一诊断变化是使用已发行Shipping文件代替返回9004的bootstrap。没有修改capture_config。Redis仍用其原配127.0.0.1:6379，端口占用时拒绝接管。

UE编排复用官方`RenderScheduler`、`RenderServiceController`和`SimProcessManager.startRenderers`（visualization/dist-bridge/bridge/server.js:78–130、sim-process-manager.js:355–427）。编排端仅下发原想定及渲染控制，不读取相机帧/全态势给算法。Node只通过官方控制服务启停UE；按本次PID清理Redis。Shipping收到shutdown成功ack后自行退出777003；不把这个收尾码误计作官方runner失败。服务退出0，没有无差别结束进程。

后续入口为`ZqhjGame/probe.cmd --ue-direct`；从脚本自身定位环境，支持`--sim-root`与项目内`--output`，支持ZQHJ_PYTHON和项目.venv，拒绝覆盖现有运行目录。`--help`可查参数。此入口是离线探针工具，不是最终单模块提交文件。

### 官方原始输出

成功回合原始文件：

`artifacts/probes/20260907-204636/official/coop_decoy_1788785330.evaluation.json`

- seed42；60秒短回合；末帧59.9833333333秒；901评分tick。
- total/base/penalty均0，n_destroyed=0/3，n_reports=0，passed=false。
- proximity/boundary事件均0；全部per_target.coop_ticks=0，dwell=0。
- 这是“图像/控制探针真实运行完成”的证据，**不是双机控制协同通过、真假识别通过或正式比赛成绩**。

`official/`同时保留SDK正常生成的种子化/导航准备场景副本。runner.log、engine.stderr.log、ue.log、render-service.log及Redis日志均在本次项目运行目录；没有读取截图目录。UE潜在默认运行产物位置`ue-renderer/Windows/testwl/Saved`记录在run.json，未将其作为观测来源。

## 图像实测

| Agent UID（仅无人机身份） | 收到photo/回调数 | 唯一bytes哈希 | 保存并完整解码 | 格式/分辨率 |
| --- | --- | --- | --- | --- |
| 20001 | 900/901 | 899 | 60/60 | JPEG / 1024×768 |
| 20002 | 900/901 | 898 | 60/60 | JPEG / 1024×768 |
| 20003 | 900/901 | 897 | 60/60 | JPEG / 1024×768 |

三路首拍无photo，后续有图。每路独立UID缓存、对应独立Agent实例、记录独立目录。依次仅改变一个Agent的云台/FOV，其自身读回和画面发生相应改变；三组接触图人工检查过，均为可见地形/场景内容，非空白或不可解码字节。JPEG实测与SDK文字“PNG bytes”不一致，消费者应按实际编码识别，不能只验PNG魔数。

云台pan 0→45度、FOV 50→15度的单机窗口分别为仿真5/10、15/20、25/30秒；35秒三机恢复pan0/FOV50。画面取景及缩放有可见变化。这是基本响应和归属的支持证据，**不是已完成相机内参/像素地理投影标定**；同时飞机在运动、天气在变化，不能只靠前后不同图片证明准确角度映射。

原始bytes在`observations/<本机UID>/<sha256>.image`；仅由本机公开photo在实例内暂存，官方run返回后离线导出。`observations.jsonl`记录每次公开self、inbox、score_sim_s、诊断墙钟、dt和返回命令。Agent不读写文件、Redis、队友对象；离线实例登记仅供结束后导出，不向Agent暴露登记表。

离线解码器使用Codex已配备的Python/Pillow12.3.0，无安装：

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\ZqhjGame\tools\analyze_perception_probe.py .\ZqhjGame\artifacts\probes\20260907-204636
```

cwd为SIM_ROOT，退出0，1.406秒。此绝对路径仅记录本机实际命令，不硬编码在工程中。其他电脑可用安装Pillow的离线分析虚拟环境运行同一工具。输出analysis.json和public-photo-20001/20002/20003.jpg，已逐张查看。

**新鲜度局限**：保存/回调时间是接收侧时间。无捕获时间戳、帧号、TTL，缓存可保留旧帧。哈希变化只证明字节更新；雪、噪声或曝光变化也会改变哈希，不能得出准确帧龄、真实采样频率、图像与位姿同步误差或端到端延迟。渲染器日志中的FPS也不能替代Agent采集时延。

## 时间、控制与通信

三机各901次回调：dt恒0.1，累加90.1秒；score_view.sim_time末值59.9833秒；从首回调至末回调墙钟约111.865秒。相邻仿真间隔中位数0.066667秒，墙钟中位数0.12433秒。本次无重复sim_time回调。官方runner.py:484固定period=.1，:527公开相对仿真时刻；**业务持续时间用合法相对仿真时间，墙钟只诊断性能**。不能把dt累加充作20秒共同跟踪。

基础控制：所有云台/FOV阶跃在下次公开观测已读回指定值（本次相隔0.0667–0.0833仿真秒，这不是精确执行延迟）。35秒fly_to仅用各机起始合法位置北偏250m，后续航向/轨迹改变；未投喂目标真值。45秒速度20→30，49.98秒约29.904m/s；50秒恢复20，54.98秒约20.095m/s，末帧约20.0006。高度约500m。无新指令期间云台/FOV保持，速度响应有过渡，不能推导精确动力学模型或所有命令速率。SDK-API.md:445–446明确60/30度每秒速率只约束内部auto_track，不能套在选手point_gimbal上。

通信实测（每机一致，payload均由公开构造器产生）：

- 仿真3–24秒按墙钟≥.30秒发送B序列：106次尝试，76个自身广播回环，30次rejected_rate。每条发送间隔约.37墙钟秒，按墙钟和固定dt累加均低于4Hz，仍被限频。
- 仿真26–34秒按score_sim_time≥.30秒广播S序列：24条均回环；中间区间统计18发送/0限频。与上项对照，**结果支持通信按引擎仿真时钟限频，而非回调dt或墙钟**；C++源码未发行，不能宣称已精确还原滑窗边界、内部取时及拒绝是否入窗。朴素4条/1秒滑窗拟合仍有边界不一致，原始对照见clock-comm-analysis.json。
- 仿真36–42秒用公开send_to对经广播发现的peer发送D序列，每机12条。三机收件箱均0条D；sent增长但delivered/received不增长，rate/range/jam/bytes拒绝计数均未增加。SDK commands.py:132–138生成peer_target_unique_id，client.py:98–107原样发布；未找到发行C++来解释。**定向投递未通过**，未猜私有字段、未修改SDK。
- 每机总sent142并不等于成功送达：100条成功广播+30条限频+12条未送达定向。received/delivered各300。每机唯一自消息100、唯一队友消息200；实例内按(sender,协议序号)仅处理队友200次，重复分别忽略18160/17347/17347次，自回环明确忽略。inbox是历史队列，不能每拍重消费；本探针短期集合有界，生产协议还需epoch/TTL/容量管理。
- recv_time与公开相对仿真时间同量级，历史消息比当前时刻旧；它是接收时刻，不能直接当发送时刻。未来跨机轨迹需在≤50字节协议中主动包含合法仿真时间。

另一个限频是**裁判目指上报**：_vendored/coop_eval.py:577–628使用传入sim_time与_last_report_time差值1秒，团队共享裁判目标配额；runner.py:651–714传原始仿真时刻，时间差不受原点影响。本轮没有发report_target，故这里只是源码确认；不能称实际报告限频已测试。YOLO结果max_age使用墙钟，又是另一种时间基准。

## 验收清单与下一步

**已通过**：公开三机photo可达、180张JPEG完整解码、1024×768、独立归属的源码与基本响应证据；云台/FOV/导航/速度基本响应；三种时间区分；广播可达、去重与自消息处理；一次真实60秒运行和原始官方评分输出。

**未通过/未执行**：官方bootstrap启动9004；send_to定向投递失败；像素→地理候选位置未标定/验证；默认YOLO三机正确绑定未通过源码核验；未运行YOLO或真假识别；未测精确图像延迟；本轮未跑双机共同观察或600秒自研算法回合。没有用mock或模拟检测补齐视觉通过结论。

双机实验停在两个明确缺口：通信完整探针中定向投递失败；目前只有图像传输，没有经过验证的视觉候选坐标供第二机对准。后续协调可用已验证broadcast的逻辑收件人；但这不能替代视觉定位前置验证。控制协同与真假识别继续分别验收，官方per_target.coop_ticks/dwell/清除才用于结论。

**需主办方确认**：

1. 正式评测具体发行版本、三机UE/photo是否全部提供，分辨率/帧率/FOV定义、丢帧/时间戳与GPU预算；无图时是否仍回退模拟检测。
2. eval默认首机绑定、自定义sensor仍启动默认worker的本地冲突是否已修复；正式加载参数和是否强制指定yolo_model。
3. 模型权重能否随单模块Agent作为独立附件提交，大小/格式、离线加载路径、内存/显存/耗时及允许依赖。
4. 默认位置反算中的机头/云台坐标、实际FOV、地形高度、图像与姿态时间对齐；不自行认定本地近似函数就是正式精度合同。
5. send_to的公开参数/本版不送达是否为已知问题；通信滑窗精确基准/边界；photo文档PNG与本机JPEG不一致。

**下一步只实现一个功能**：本机photo到单个候选位置的最小定位探针，带无检测/缺帧处理与不确定性，先验证像素方向、云台坐标/FOV和地面投影。它不判真假、不做任务分配、不训练。候选位置闭环成立后才用保守仿真时间广播接入一次双机观察。

最终复核：原审计60个官方文件SHA-256全部不变，新增审阅的官方渲染编排/视觉源码另存指纹；3实例的rows/photos/seen/peers容器互不共享，新增Python文件语法与导入通过。证据见同回合final-verification.json。final-process-check.json确认无残留UE/引擎/Redis进程及6379监听，Git仅显示原有未跟踪ZqhjGame。最终离线分析命令退出0/1.241秒，完整命令记录位于artifacts/checks/20260907-205708-333187-photo-analysis-final/command.json；probe.cmd --help退出0。没有为最终工具元数据/分析输出修改重复运行引擎。
