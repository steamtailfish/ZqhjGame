# 本机photo候选与位置估计：本轮验收

日期2026-09-07；沿用PROJECT_PLAN.md主路线，不重新审计路线。本轮交付的是**可拒绝的投影组件，以及真实图像上的离线条件几何样例**。在线自动候选与采集时刻对齐未通过，因此目前不具备进入最小双机目标观察的条件。

## 1. 继承证据与新增范围

先读取PERCEPTION_CONTROL_VALIDATION.md、上一轮run.json、runner-call.json、recording.json和公开接口源码。上一轮三机JPEG 1024×768、控制基本响应、广播/去重成立；send_to未送达、无bbox/深度/采集时间戳、默认YOLO首机绑定等限制没有消失。上一轮飞机持续转弯，不作为本轮稳定相机标定已通过的依据；没有重跑其60秒控制/通信实验。

本轮唯一新增引擎实验：seed42、42秒，三机各自先飞向**本机合法初始位置北偏1000m**、speed15、pan0/tilt-90/FOV50；18秒FOV30；26秒tilt-60/FOV50；34秒pan30。所有命令由公开构造器生成，没有目标真值、固定目标ID、隐藏地形/路线输入，也没有通信或上报。sensor显式SKIP_DETECTION，不使用模拟感知经纬度作对照或定位真值。

真实运行目录：`artifacts/probes/20260907-213142`。官方runner退出0，631tick，末帧41.983333秒；包含启动/收尾96.082墙钟秒。三机各631回调、首帧缺公开时间/photo，其余630拍接收到不同于上一拍的bytes，每机保存90张。未把bytes变化计为精确采集帧率。

官方原始输出：`official/coop_decoy_1788787996.evaluation.json`：0分、0清除、0报告、0惩罚。这是正常真实采样完成证据，不是定位精度或双机成绩。

## 2. 时间与像素来源

`src/zqhj_localization.py:7–48`的ObservationClock直接保留`obs.briefing.score_view.sim_time`，不按Agent起点重新置零、不使用固定dt累计。首帧缺失、无效值、相同时间、>1秒间断、回退、相同bytes分别记录原因；reset清除本实例历史。1秒是本探针的拒绝阈值，不是赛事时间规则。重复/间断/回退分支由合成测试覆盖，本轮实采确认的是首帧缺失与正常推进。

- `observation_sim_s`：公开观测对应的本局相对仿真秒。
- `receipt_first_seen_sim_s/wall_s`：该bytes与上一拍不同时，本实例首次看到它的时刻；不是SDK后台缓存收帧时刻，更不是相机采集时刻。哈希不是帧号；内容重现也不证明是新采集。
- `capture_sim_s/capture_wall_s`：本机接口没有提供，保持null。
- `observation_wall_s`：perf_counter单调墙钟诊断值，不用于跨机TTL。
- 跨机TTL将来必须使用同一官方回合的公开时间和共同回合标识，不能相减两个Agent各自reset后的计时；本轮没有实现跨机TTL。

接口复查：`competition/sdk/core/observation.py:103–119,142–166`的Detection没有bbox、像素或深度；SelfView只有photo bytes及已有状态。`core/perception/photo_cache.py:54–85`返回bytes、不返回帧号/时间戳，且会保留缓存。官方YOLO辅助代码`examples/yolotrack/yolotrack/bbox_to_gimbal.py:8–43`需要外部bbox和两个FOV，本身不提供候选；SDK-API.md:197–198是占位示例，不能当真实像素检测。当前没有验证过的在线自动像素候选来源，也未安装模型推理依赖。

本轮候选来源明确为**离线视觉选点**：本助手查看已导出的原始本机photo，标注可见特征，再用离线局部模板相关核对后续图像对应。不是用户提供的标注，不是在线目标检测器，也不声称该特征是参赛车辆。标注只在tools离线实验内；Agent不加载这些代码/标注/结果。

## 3. 一个真实候选的完整证据

最终目录：`artifacts/localization/20260907-geometry/pixel-evidence-final`；完整数值在geometry-results.json，查看20001-correspondence.jpg及三张单帧标记图。全部计算使用1024×768原始像素；预览缩放仅用于展示，模板裁剪后的坐标已还原至原图。

候选为20001本机图像中的**深色区域边界直角点**；不假定它是水、道路、车辆或已知海拔标志。

| 用途 | 公开观测秒 | 原图像素(u,v) | 来源 |
| --- | --- | --- | --- |
| 建模帧1 | 9.850 | (155.000,211.000) | 离线视觉选点 |
| 建模帧2 | 14.050 | (154.874,401.978) | 同一原图块的模板对应，NCC约0.979 |
| 留出验证帧3 | 16.850 | (154.990,530.926) | 模板对应，NCC约0.985；标记图已检查是同一角点 |

NCC是纹理相似度，不是目标概率。前两帧本机公开位置水平基线约63.289m；使用本机位置、实际云台/FOV状态和像素射线做最小二乘交会，没有读隐藏高度。第三帧不参与求交会点/高度，只检查重投影。

稳定窗口（首选帧前1秒至末帧）：20001实际heading变化约3.1e-7度、pan/tilt/FOV完全不变，speed变化约5.8e-5m/s；飞机仍以15m/s平移，**稳定姿态不等于静止位置**。数据支持图像与位移的相对一致性，不证明采集时刻已知。

在声明的零roll、正下视、完整输入图像、方形像素和局部平面模型中：

| FOV50的假设 | 从前两帧反推的特征平面z（公开alt的假定同基准） | 留出帧重投影差 |
| --- | --- | --- |
| 水平FOV | 136.1505m | 1.6194像素 |
| 垂直FOV | 227.1153m | 1.6185像素 |

不能据此选择一个高度当真实地形海拔：正下视平移主要约束高度/焦距之比，两种假设都能解释数据。本次水平位置在两种假设下近乎相同，是该几何条件下的结果，不证明一般斜视也可忽略FOV。源代码没有给出公开alt相对海平面/地面或UE相机安装偏移的充分说明，未自行补齐。

留出帧候选的条件估计例（水平FOV假设）：

```json
{
  "source": "offline_template_correspondence",
  "pixel": [154.9903, 530.9257],
  "observation_sim_s": 16.85,
  "receipt_first_seen_sim_s": 16.85,
  "capture_sim_s": null,
  "position_valid": true,
  "validity_scope": "declared_offline_model_only",
  "latitude": 27.0016385822,
  "longitude": 124.9903941621,
  "temporal_alignment_verified": false,
  "online_usable": false,
  "absolute_accuracy_verified": false
}
```

此处valid只表示**候选来源/对应、声明模型、数值和留出检查合格**；不是正式在线定位通过。真实坐标的许多小数不代表同等精度。恒定未知图像延迟在直飞中可能保留相对几何一致性而使地理位置整体偏移；以15m/s计算，1秒未建模时差会对应约15m沿航迹偏移，这是敏感性关系，**不是测得延迟为1秒**。没有独立合法已知位置参考，因此不宣称绝对定位误差达标。

## 4. 坐标与投影逐项结论

| 项目 | 本轮确认程度 |
| --- | --- |
| 像素索引 | 本项目明确u向右、v向下，整数代表像素中心，主点假设((W-1)/2,(H-1)/2)。原始图为1024×768，未用缩略图坐标求解。主点/畸变没有独立标定。 |
| 像素方向 | 正下视直飞中同一静态点向图像下方移动，与本机前进的针孔模型一致；仍不是所有姿态/roll都已验证。 |
| pan与机头 | 20001近正北航向无法区分world_pan与heading+pan。额外查看20003自身图像的环状纹理点：航向约2.54度，heading+pan的留出差约1.00px，world_pan约10.73px，支持机头相对pan。该点NCC下降到0.71，作为支持证据保留，**未提升成完整坐标合同**。各机独立求解，未用其他Agent位置补本机估计。 |
| tilt | SDK-API.md:402明确下为负；本次实际-90/-60读回及画面改变。几何有效样例仅验证-90附近；斜视-60的完整投影仍未通过。没有沿用默认工具对tilt取abs的做法；朝上/近水平直接拒绝。 |
| 状态与命令 | 只用原始公开self状态计算，返回命令仅作为动作记录。FOV/姿态变化的切换窗口不用于本次有效样例。 |
| FOV | 用各帧实际50度，另记录30度阶段；未固定60/45度。水平/垂直定义仍有不可辨识性，分别输出假设；30度的定量内参校验未完成。 |
| 裁剪/缩放 | 项目处理原始完整JPEG，计算链无缩放；NCC局部搜索不改变原图坐标。UE上游是否有隐藏裁剪、FOV映射或非方形像素无直接证据，保持模型假设。 |
| 高度 | 使用观测约500m，未用旧200m。特征平面高度只由同机两幅photo和自身位移估计；不读取地形/真值/路线、不默认为0、不称其为已知海拔。 |
| 图像与状态时间 | first-seen与capture严格分开。稳定控制、两帧视差和留出一致性支持本次**条件近似**；采集姿态与绝对帧龄未核验，不能把接收状态当已验证的拍摄姿态。 |

## 5. 有效性与拒绝机制

`src/zqhj_localization.py:51`定义CandidatePixel，记录source/detail、u/v、原图尺寸、SHA-256和本机UID；`:74`用针孔射线（不采用线性角度近似），`:86`交会已明确来源的局部平面。ENU为东/北/上；地理输出用局部经纬近似。FOV轴、yaw约定、高度、稳定性与证据必须由调用方显式给出，没有偷偷默认官方几何已通过。

拒绝：来源不明、离线标注用于在线、UID/图片哈希不符、缺失/非有限值、像素越界、未知裁剪、姿态不稳定、无几何证据、地面高度/基准缺失、时间缺失/重复/跳变、相同bytes、朝上/近地平线、相机不高于地面、超投影范围/近极点。在线即使给出一个采集时间戳，也必须另有经过验证的相应时刻姿态，不能自动用当前self代替。

真实候选结果文件含两个条件有效估计以及三种拒绝示例：

- `online_rejection`：同一真实候选不能当在线输入，且采集姿态未知；坐标为null。
- `unknown_height_rejection`：去掉来源高度后拒绝；这是对真实输入的条件屏蔽检查，不是声称引擎真的丢了某个公开高度字段。
- `unstable_pose_rejection`：明确不接受稳定性条件时拒绝；同样是拒绝分支演示，不冒充该稳定样例发生了姿态故障。

此外首回调真实缺时间和photo，ObservationClock直接拒绝。不是所有情况都返回无效，但当前所有离线估计均禁止直接用于在线策略。

## 6. 命令、文件与验收记录

实际cwd均为`D:\catkin_ws\hf2026-sim-windows`。在线/引擎解释器仍是包内Python3.12.13；离线图像分析使用已配备Codex Python的Pillow和NumPy，未安装依赖。

```powershell
.\ZqhjGame\probe.cmd --ue-direct --probe geometry

# 公式及异常分支；非真实成绩
.\python\python.exe -B -X utf8 .\ZqhjGame\tests\test_localization.py

# 图像离线分析；本机实际分析解释器见command.json
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B .\ZqhjGame\tools\validate_pixel_geometry.py .\ZqhjGame\artifacts\probes\20260907-213142 --output .\ZqhjGame\artifacts\localization\20260907-geometry\pixel-evidence-final
```

最终合成检查13项通过，记录`artifacts/checks/20260907-214154-093988-localization-final-tests`。最终真实图像分析退出0，0.281秒，记录`artifacts/checks/20260907-214154-389461-real-pixel-geometry-final`。首次离线分析因未过滤首拍None时间失败，记录213839保留；已修正，仅重算现有图像，没有重跑引擎。像素对应图已逐张查看，final/visual-review.json记录范围与局限。

新增：src/zqhj_localization.py、src/zqhj_geometry_probe.py、tests/test_localization.py、tools/localization_evidence.py、tools/validate_pixel_geometry.py及本报告。更新tools/run_perception_probe.py以选择geometry模式，默认control模式保持60秒；更新STATUS和SDK合同的相关状态。未重写PROJECT_PLAN，不增加空算法目录。

公式/拒绝分支通过；真实图像条件几何样例通过。**在线自动候选、相机FOV/高度基准完整标定、采集姿态对齐、绝对精度仍未通过或未确认；暂不进入最小双机目标观察。** 下一步缺口是合法在线像素候选来源及能支撑在线使用的图像—姿态合同，不能把本次离线标注或拟合高度写成在线常量。

结束复核：原审计60个官方文件哈希全部未变，6个相关Python文件语法通过，运行进程与6379监听已清理；记录在本次run目录的localization-final-verification.json和final-process-check.json。结束时Git另显示未跟踪YOPO/目录，本轮没有创建、读取或修改它，保留用户工作。
