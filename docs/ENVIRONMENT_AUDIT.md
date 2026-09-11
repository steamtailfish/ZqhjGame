# 2026-09-07晚增量结论

本页早期“未启动UE/图像未验证”等段落保留为首次审计历史。最新真实感知与控制结果以[PERCEPTION_CONTROL_VALIDATION.md](PERCEPTION_CONTROL_VALIDATION.md)为准：UE增强版三机photo已实测JPEG 1024×768，seed42真实60秒探针通过运行验收；官方bootstrap返回9004，包内Shipping直接启动成功；定向send_to未送达；无双机/真假识别通过结论。新增入口probe.cmd。官方环境与依赖未手工修改，未安装Python/YOLO依赖。

---

# 环境与赛题审计

审计日期：2026-09-07，Windows 11。本文件中的官方相对路径均从 SIM_ROOT 起算，`ZqhjGame/` 为自研项目。代码行号对应本次发行包，升级后需重新核验。

证据等级：**手册明确**＝原始 Word 的文字/表格/图片；**SDK/源码确认**＝本地公开 Python、脚本、配置的实际实现；**实验观察**＝保存日志的本机试验；**待确认**＝未发行的实现或未执行的通路。源码说明本地行为，不能替代正式比赛规则。

## 1. 实际目录、版本和修改边界

| 项目 | 实际结果 |
| --- | --- |
| SIM_ROOT | `D:\catkin_ws\hf2026-sim-windows`：同时存在 VERSION、SDK-API.md、competition、opensim-sim.exe、Windows脚本 |
| PROJECT_ROOT | `D:\catkin_ws\hf2026-sim-windows\ZqhjGame`：原有目录，审计开始时为空 |
| Git | 官方根仓库；初始工作区干净；提交 `4346c8b26f3fbe97b2c071ce82a73f0d940fca40`（2026-09-04，提交说明更新 v2.0.3 UE win） |
| 适用 AGENTS | 已检查盘根、上级目录、SIM_ROOT、PROJECT_ROOT；原来未发现适用 AGENTS.md，项目文件为本轮新建 |
| 旧规划 | 定向搜索未找到 `ZqhjGame_Codex_Project_Plan.md`，不能对不存在的方案声称完成逐条比对 |
| VERSION | OpenSim 2.0.3；Build `2026-09-03T09:45:29Z`；win-x64；最低 Windows 10 1809 |
| README | 仍标 2.0.1、Ubuntu/Linux 路径，与本包不一致；Windows运行以实际脚本和二进制验证为依据 |
| 手册 | V2.0.2，正文 B0005；与软件版本单独记录 |
| 类型 | **UE 增强版**：存在 `ue-renderer/Windows/testwl.exe`、UE启动配置，Git版本说明一致 |

所有自研写入、运行日志、端口适配场景副本、随机场景副本和评分均在项目内。未执行 setup/start/stop，未修改任何官方文件，未建仓库、移动工程或清理旧产物。原有 `run/`、logs、场景备份属于审计前状态，保留。

可用校验见 `release_manifest.json`：60个相关文件的尺寸和 SHA-256、Git提交、解释器和依赖。包括引擎、Redis、SDK、基线、原场景、地形数据。本地 LFS pointer 可核对部分大文件；这些是本地一致性证据，不是主办方签名或独立发布校验。未找到另行提供的整包校验清单。哈希记录不表示逐行阅读了二进制或地形内容。

## 2. 手册完整性

原件：`红枫2026无人集群自主协同智能算法挑战赛参赛手册.docx`。SHA-256：`d0f81b5163f6121a66090d956dd0b6161bfd241ea7307907265d5f1e787fa5b3`。

`tools/extract_manual.py` 解析原始 OOXML，输出到 `docs/manual/`：有序正文 `MANUAL_EXTRACT.md`、结构化 `body.json`、完整性 `manifest.json`、原嵌入媒体。已阅读全部186个正文顶层块、5张表的全部行列、2张相关嵌图和页脚；footnotes/endnotes未含实际正文，未发现OLE或修订内容。两图已分别打开检查：image1.jpeg 为真目标银色轿车示例，image2.png 为银色MPV/箱式诱饵示例。外观示例不构成稳定目标身份特征。

**未完成的版式检查**：没有安装可用的 Word/LibreOffice 页面渲染器，未渲染整份分页、目录页码或精确页布局。本轮是内容审读，未遗漏已发现的表格/图片；不宣称完成分页视觉校对。Bxxxx/Txxx/Rxxx 是提取器位置标识，不是原文页码。

| 手册位置 | 内容与赛题范围 |
| --- | --- |
| B0027–B0032，通用任务描述 | 信息隔离、视觉辨别、真假均可移动；其中单机20秒描述不能替代赛题二的K=2专条 |
| B0040/T001、B0043–B0045 | 标准/UE双版本；Windows；Python3.10+、redis、pyyaml |
| B0062 | 通用地形范围、固定500m、15–40m/s、FOV5–50度、30度/秒转弯 |
| B0075–B0085，赛题二 | 3机独立Agent、3真+15移动诱饵、600秒、双机同时跟踪、通信和坐标上报 |
| B0114、B0117、B0124 | CLI、赛题二基线名称、dry-run说明 |
| B0129–B0134 | 单模块Agent、依赖说明、技术报告≥2000字；最终客观90%/创新10%、新路线验证 |
| B0140–B0141 | K=2/20秒、≤2秒中断保留回补、>2秒清零；逐目标RMSE、每目标每秒1条、尸体报告丢弃 |
| B0147/T004、B0150 | 赛题二0.5/0.3/0.2权重，120m、240/420秒；距离/越界惩罚描述 |
| B0153–B0163、B0178–B0179 | 合法三层观测、实例状态、无真值、无目标摧毁标志；前端全态势仅人工调试 |
| B0171、B0173 | 真车/诱饵嵌图 |

赛题三的SAM、干扰区、10目标和生存维度没有加入本项目赛题二要求。通用观测里存在 jammed/zone 字段，不表示赛题二当前场景有这些威胁。

## 3. 已读官方资料与范围

- 文档：`SDK-API.md` 全文578行、`README.md`、`VERSION`、`competition/user_algorithms/README.md`、`config/models/README.md`、YOLO示例依赖说明。
- Windows脚本：`setup.ps1`、`start.ps1`、`preflight-check.ps1`、`verify.ps1`、`stop.ps1` 全文；已有 `run/env.ps1` 仅用于了解端口配置。
- 启动/接口：`competition/__main__.py`、`sdk/cli.py`、`sdk/core/{agent,observation,commands,isolation,runner,client,world_state,scoring,scenario_randomizer}.py`；core/perception 下 base、resolver、photo_cache、default_detectors、bbox_to_latlon。
- 赛题二：`sdk/scenarios/coop_decoy/{__init__,agent,observation,runner}.py`；`baselines/coop_distributed.py` 全文425行；原 `competition/scenarios/coop_decoy/scenario.json` 的UAV、实体类型/数量、天气/识别配置，`config/algorithm.yaml`。未无目的逐一抄录所有目标起点/路线。
- 裁判/运行：`sdk/_vendored/{sim_runner,coop_eval,uav_target_map,score_publisher,metrics_summary}.py`；`_astar_navigator.py` 定位入口并读实际批量规划/派发相关段417–744，未逐行审查无关辅助函数。
- 配置：`config/defaults.json`、`models/uav.json`、`models/gimbal.json`、`terrain_bbox.json`、`renderers/ue_testwl.json`、UE capture_config.json；`schema/sim-commands.schema.json` 全文和 sim-state.schema 的相关定义。
- 示例检查：`examples/_common/tests/score_e2e_smoke.py`、`test_coop_eval.py` 的相关用例用于定位官方可用检查。**examples/_common/coop_eval.py 与运行时 sdk/_vendored/coop_eval.py 哈希不同**，示例测试不能直接证明当前裁判正确；本轮合成探针直接导入运行时版本。

未提供/未检查：引擎的运动、云台几何、命令接收、通信限速和UE服务底层源码；源码注释引用的 `contracts/*.md`、`specs/*` 在本包定向检索未找到相应接口合同原文；没有独立新版本变更日志可替代版本文件/Git说明。未反编译；未审查前端打包产物、第三方库、UE资源内容。前端、UE、正式裁判部署环境及其私有规则仍不可见。

## 4. 实际运行链路

```text
ZqhjGame/run.cmd → tools/run_competition.py（定位根目录、隔离产物、启动本次专用Redis）
  → cwd=SIM_ROOT，PYTHONPATH=SIM_ROOT + PROJECT_ROOT/src
  → python -m competition run --scenario coop_decoy --agent module:Class
  → sdk/cli.py 选择赛题二 runner、加载类
  → CoopDecoyRunner.prepare_scenario：准备副本/随机路线、RunnerBase 启动真实引擎
  → 等 sim:commands 订阅者和第一帧；注入18辆车A*；创建3个Agent
  → 每机隔离观测 → photo（如有）→ sensor/default detector → decide
  → 普通Command按顺序发引擎；agent.report仅交给评分器
  → 全状态几何关联 + K=2跟踪裁决 + 上报RMSE + 惩罚
  → 停车清除已摧毁真车；sim:score实时快照
  → *.evaluation.json + 原始score_timeline；停止本次子引擎/Redis
```

源码入口：`competition/__main__.py:6`、`competition/sdk/cli.py:49`（加载器）、`:179`（分派）、`sdk/scenarios/coop_decoy/runner.py:244`（赛题参数）、`sdk/core/runner.py:354`（主流程）、`:438`（实例）、`:551`（回调）、`:587`（执行）、`:651`（评分投影）、`:629`（JSON）。默认场景常量来自赛题二 `__init__.py`，不是猜测的场景名。

原CLI支持 `--scenario-json`，工程使用原场景；独立Redis端口不同时仅在项目副本调整 simulation.redis_host/redis_port。官方 runner 随后在输出目录生成自己的准备场景，不改原场景。随机路线副本仅为离线运行证据，不允许在线Agent读取。

加载器支持 `module:Class`，先 import 原模块，再尝试 `competition.` 前缀；不支持直接把 `.py` 路径当类名。`src/zqhj_entry.py` 可被合法导入，不需要复制到 competition。`algorithm.yaml` 在这一 CLI 链路没有加载点，configure 实收 `{}`；规划不得假设有自动YAML注入。

## 5. Python、服务与运行决策

| 检查 | 结果 |
| --- | --- |
| 本轮实际解释器 | `SIM_ROOT/python/python.exe`，Python 3.12.13，64位；完整实际路径见run.json |
| Python依赖 | redis 8.1.0、PyYAML 6.0.3、pip 26.1.2；导入通过，无新增安装 |
| 系统PATH Python | `D:\Softwares\anaconda3\python.exe`，3.13.9；有yaml而无redis，未改动 |
| Redis服务端 | 发行包 bin/redis-server.exe，实际 INFO 显示8.8.0；手册7.4.2为版本不一致 |
| 初始服务 | 配置端口6379/8080/8081/8082/3000未发现活跃官方服务；其他Codex/系统进程保留 |
| 图形环境 | Windows11 Pro build26200；RTX4080 SUPER，驱动32.0.15.9579；未以此代替UE实跑验证 |
| 工具 | Git及git-lfs可用；未全局pip安装，未新建.venv |

官方脚本风险来自**实际代码**：start.ps1:115–183 宽范围清理进程、:215–247改各原场景端口、:448–462改UE配置；stop.ps1:53–64恢复场景、:73–90宽匹配清理、:123–155处理端口Redis。setup.ps1 包含安装和用户级pip步骤。依照本任务修改边界，这些脚本未执行；入口使用原CLI和现有依赖，独立管理自己启动的进程。

执行 `powershell.exe -NoProfile -File .\preflight-check.ps1` 被 Windows PowerShell 执行策略拒绝，退出1，官方检查正文并未运行。没有使用 Bypass、修改策略或关闭安全限制。后续读取配置、二进制启动、依赖导入和真实CLI运行独立提供证据；不将它们称为官方preflight通过。`verify.ps1` 还依赖前端服务并选择系统Python，本次无前端而未运行。

调用 `opensim-sim.exe --help` 后二进制未显示help，而尝试默认 config.json 并因缺失退出1；只证明程序能加载，不能视为CLI帮助通过。实际引擎参数从 `sdk/_vendored/sim_runner.py` 和 runner 启动调用核验。

## 6. 复现入口和证据

任意工作目录下，以真实项目路径调用 `run.cmd`。以下是从 SIM_ROOT 执行的例子，具体解释器、工作目录、展开的完整CLI、环境变量、种子、退出码和耗时自动保存到每次 `run.json`：

```powershell
.\ZqhjGame\run.cmd help
.\ZqhjGame\run.cmd check
.\ZqhjGame\run.cmd score-smoke
.\ZqhjGame\run.cmd dry-run --seed 42
.\ZqhjGame\run.cmd smoke --seed 42 --redis-port 6380
.\ZqhjGame\run.cmd baseline --seed 42 --redis-port 6380
.\ZqhjGame\run.cmd dry-run --seed 42 --agent zqhj_entry:EntryAgent
```

`--sim-root "完整官方环境路径"` 可覆盖官方根；`--python "解释器路径"` 选择运行CLI的解释器；启动器自身默认优先 `ZQHJ_PYTHON` 环境变量、项目 `.venv`、父目录官方 Python。跨发行包且父目录没有Python时，先设置 `ZQHJ_PYTHON`。`--output` 的相对路径始终相对项目，只接受项目内新目录，不覆盖旧记录。内部 cwd 始终切到 SIM_ROOT；项目与SIM_ROOT统一在启动器设置 PYTHONPATH。已验证中文/空格输出目录；外部cwd/显式路径验证见 STATUS。

新机器保留官方包版本，重新建环境（以下**安装步骤本轮未执行**）：

```powershell
# 在 SIM_ROOT；选择已安装且兼容的Python，不依赖复制.venv
python -m venv .\ZqhjGame\.venv
.\ZqhjGame\.venv\Scripts\python.exe -m pip install -r .\ZqhjGame\requirements.txt
.\ZqhjGame\run.cmd check
```

requirements.txt 固定本轮验证的两个Python直接依赖；Redis服务端和引擎由发行包提供。YOLO/UE视觉额外依赖不在本轮安装范围。下载依赖需要网络时据实记录结果；不通过修改官方逻辑规避故障。

`score-smoke` 原样执行发行包 `python -m examples._common.tests.score_e2e_smoke`，仅验证真实Redis发布/接收6条人工构造评分消息，强制该脚本要求的6379专用端口。它不运行引擎、不写真实比赛评分文件，不能引用其中的80分作为基线成绩。

每次真实运行保存 `console.log`、`engine.stderr.log`、`redis/`日志、端口场景副本（需要时）、`official/`随机场景和原始评价JSON。SDK将引擎stdout重定向到DEVNULL，入口无法取得其完整stdout；没有伪造空白stdout为“全部引擎日志”。本轮引擎stderr为空也如实保留。Redis只本机绑定、开启protected-mode、不持久化；仅终止所持Popen句柄。Redis在Windows/MSYS报告的内部process_id与Windows PID可能不同，不用该内部数字杀进程。

## 7. 规则/实现冲突与优先待确认事项

| 问题 | 手册/文档 | 本地源码/实验 | 项目决策 |
| --- | --- | --- | --- |
| 双机协同与移动诱饵 | 手册B0075–85、B0140：K=2、移动诱饵 | baseline.py:11、:21、:299仍以静止诱饵/K=1分区为假设 | 不改官方基线；自研从K=2重新设计，不能用运动即真目标 |
| 距离/越界惩罚 | B0150描述持续累计、越近扣越多 | coop_eval.py:521–555仅进入违规区计次，每次2分，封15；合成探针验证 | 正式口径待主办方确认；策略保持保守安全间距，不利用持续违规只扣一次 |
| 任务耗时原点 | B0147：全歼相对240/420秒 | runner.py:603/651传原始时间；coop_eval.py:474/679/724直接比较原始destroyed_at；本机初始-28800 | 合成300秒全歼在原点0/-28800/1780000000得到66.67/100/0；记录缺陷，不修评分，不把合成结果当成绩 |
| 边界 | B0062近似地形范围 | briefing硬编码26.98–27.02 /124.98–125.02，实际评分terrain_bbox约26.98180556–27.02500868 /124.98–125.0203125 | 区分任务区域与裁判地形边界，向主办方确认正式合同 |
| dt | SDK-API.md:298称距上次decide秒数 | runner固定传0.1；墙钟和真实仿真时间均可不同 | 不以累计dt作严格仿真计时；合法score_view.sim_time处理缺失/重复 |
| 收件箱/统计 | observation.py:122/:173描述本周期 | 实测历史32条跨帧重复、自广播回环、统计累计；isolation未去重 | 协议加序号/TTL、去重及自消息处理；统计做差分 |
| 云台动力学 | SDK-API.md:402称瞬时无转速限制 | gimbal preset列60/30度每秒及FOV上限120（通用预设），引擎实现未提供 | 参数存在不证明比赛生效；实测角度响应和坐标约定列后续小实验 |
| 图像/YOLO | SDK描述PNG和多机/预留通路 | PhotoCache仅取bytes无格式/时间校验；当前默认YOLO绑定首机；UE配置max_aircraft=3但未运行 | 已有合法photo入口，但未证明本机三路图像或正式视觉评分可用 |
| 同种子复现 | CLI正seed固定一部分初始化 | 诱饵RNG无seed，感知RNG未注入seed；部分派生还用hash(uid) | 能复现版本/命令，不承诺同seed逐帧/同分；禁止改随机机制 |
| dry-run | 手册B0124称不启动引擎的空转 | CLI默认start_sim与dry_run独立；ScorePublisher仍访问Redis | 显式 --no-start-sim，并启专用Redis；dry-run不算真实成绩 |
| 契约文件 | commands.py引用schema/specs | 发行schema只包含较老通用verb，SDK并未用它做全量验证 | 以实际SDK构造器作允许接口，底层拒绝/钳位待物理实验 |

`config/terrain_bbox.json` 本机已有；评分缓存缺失时底层可能写官方目录，入口要求文件存在，避免首次评分静默生成官方配置。不能自行改裁判边界或新建替代评分逻辑。

## 8. 本轮验证状态

逐项命令、失败记录和最终成绩见 `../STATUS.md`，原始记录在 `../artifacts/checks/`、`../artifacts/runs/`。静态阅读、Python导入、当前SDK合成合同探针、自研模块dry-run和真实引擎短回合已通过。完整基线的终态以 STATUS 中原始官方JSON为准；UE/YOLO视觉评测未执行。
