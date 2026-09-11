# ZqhjGame 工作约定

- 2026-09-11已取得首个非零正式成绩：score-v22，seed101，请求600秒/记录599.917秒，9.06分、2报告、0清除、0惩罚，RMSE11.27米。原始evaluation位于artifacts/vision/runs/score600-v22-seed101/official/，训练推理命令见FIRST_SCORE.md。本轮先拿分目标完成；后续优化须保留此冻结包，不得把精度分称为K=2捕获成功。

- 最新用户优先级为先取得非零正式分数，再优化高分。当前训练与推理命令及实测以FIRST_SCORE.md为准；旧score-v12历史见SCORE_OPTIMIZATION.md。不得以检测mAP、开环回放上报或OBSERVE状态代替正式evaluation和引擎K=2/20秒判定。
- 用户授权的独立只读判定记录工具tools/record_judge_trace.py仅供回合结束后的外部诊断，不得被Agent导入，不得把真值、隐藏路线或判定目标ID反馈给在线策略；当前运行包固定不变。其部分时间段记录不能冒充全回合遥测。

- 项目保持在官方发行包的 `ZqhjGame/`。默认 SIM_ROOT 为本目录父目录；入口允许 `--sim-root` 覆盖。不要创建第二份工程或嵌套 Git 仓库。
- 自研代码、工具、配置、文档和测试仅写本目录。保留已有修改；禁止 reset/clean、覆盖原工作。官方 SDK、引擎、基线、评分和原始场景只读；确需修改时说明原因、影响和替代方案，等待用户确认。
- 运行产物优先放 `artifacts/`；官方运行不得悄悄修改原场景。只管理当前入口自己启动的进程，不使用全局 Python/Redis 清理。不要执行未经审查的官方安装/启动/停止脚本。
- 在线 Agent 仅用 `obs.self`、`obs.comm_inbox`、`obs.briefing` 和实例自身状态。不得读 Redis、场景/路线文件、评分真值、截图目录、前端态势或其他 Agent 对象；不得硬编码目标 ID 或种子路线。队友信息必须经合法通信取得。
- 赛题二：3 机、K=2、连续跟踪20秒、容忍短中断2秒、600秒回合；50字节 UTF-8 / 4Hz 通信；高度500m、速度15–40m/s、FOV5–50度。手册与本地实现冲突见审计，不利用评分缺陷。
- `run.cmd help/check/test/score-smoke/dry-run/smoke/baseline` 为工程入口；自研模块用 `run.cmd agent --agent zqhj_entry:EntryAgent`。入口统一 cwd/PYTHONPATH；禁止算法模块散落 sys.path 修改。EntryAgent现为论文启发的解析协同控制基线，详见docs/PAPER_GUIDED_IMPLEMENTATION.md；test不启动引擎。
- 新依赖优先项目 `.venv`，不可全局安装；新机器重建虚拟环境，不复制本机环境。
- 必读：`docs/ENVIRONMENT_AUDIT.md`、`docs/SDK_CONTRACT.md`、`docs/manual/MANUAL_EXTRACT.md`、`PROJECT_PLAN.md`、`STATUS.md`。接口/评分改变须回读对应官方源码并更新证据位置。
- 报告分开列出静态、导入、合成检查、dry-run、真实引擎短回合和真实完整回合；没有原始官方 evaluation JSON 就没有真实成绩。最终交付保留单模块 Agent 导出与回归阶段。
- 当前路线：D感知前置验证、A主路线、B局部改进；不移植完整YOPO/Tracker、不默认开展大规模训练。用户后续明确要求YOPO引导学习，允许在独立`.venv-learning/`中实现与验证梯度训练，最新证据见docs/GUIDANCE_LEARNING.md；合成权重不得自动接管Agent。新感知证据必读 `docs/PERCEPTION_CONTROL_VALIDATION.md`；`probe.cmd --ue-direct` 为固定seed42/60秒探针，按需运行，非默认批量回归。photo只能来自本机公开观测；回调只暂存实例内证据，离线工具于回合结束后导出。
- 2026-09-10用户明确要求直接参考两篇论文开始构建：已实现A的观测/通信/协同与解析局部规划。不得把这一开发进度写成D视觉、真实K=2或论文训练算法已通过；当前不对未核实候选上报。
- 用户后续要求比赛完整适配及训练/推理命令：v0.3已授权用真实公开观测训练并经`--submission`执行网络推理，主合同为51维`coop-decoy-guidance-v3-51`。命令与验收见TRAINING_AND_INFERENCE.md；旧35维合成权重不得部署。当前整赛题的视觉数据/标定仍缺，不得以控制链路通过宣称正式视觉或K=2达标。
- 用户要求在本目录继续并自行安排路径。视觉入口为vision.cmd，相关权重/数据/配置/日志放artifacts/vision/；仅在.venv-learning安装Torch/Ultralytics，视觉测试放learning/test_vision.py，不使官方解释器的tests依赖Torch。每机初始化私有模型，回调只读自身公开photo；当前单类候选不等于真假身份，不允许以模型预测未经审核生成训练真值。命令及验收见VISION_TRAINING_AND_INFERENCE.md和docs/VISION_INTEGRATION.md。

- 最新增量：受控采集仅改artifacts/vision/fixtures内副本，类别标签只用于离线审核训练，在线不得读fixture-manifest或场景。已实际训练双类模型；同布景验证不能证明泛化。MotionPlane默认实验性，capture_verified=False；报告需显式开启且通过身份/时空/负责人门限。visual-v8改用公开fly_to执行自身规划方向，单独set_heading在实测中未按期望响应。最新证据docs/VISUAL_CLOSED_LOOP.md，历史视觉说明以时间区分。

- 最终visual-v9（微调视觉）600秒运行完成：0分/0清除/0报告，2次机间距离事件扣4分，未形成K=2。68项回归不代表任务或安全达标。用户明确质疑端到端与mAP，已确认当前只是结构化轨迹网络+独立检测的模块化基线；端到端视觉任务梯度尚未实现，见docs/YOPO_SCOPE.md。
