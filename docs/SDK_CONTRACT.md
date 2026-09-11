# 三机RGB自研入口增量（2026-09-10）

新增 `zqhj_photo_entry:PhotoEntryAgent`，由 `vision.cmd run` 离线加载每机私有视觉模型和现有神经控制器；已完成两个60秒真实RGB回合。sensor始终返回[]，像素结果保留于实例，decide候选钩子也屏蔽SDK地理检测，因此未被默认首机YOLO/模拟检测混入。地理定位/真假识别/K=2仍未通过；时间线不完整的20秒尝试被明确判为失败。详见VISION_INTEGRATION.md。

# 自研入口增量（2026-09-10）

EntryAgent已从空动作壳升级为论文启发的解析协同控制基线，接口未变；只使用下述合法字段和公开命令。新增协议为41字节ASCII/2Hz广播，含发送仿真时间、序号和原观测年龄；从历史收件箱去重，不调用尚未验证的send_to。算法实现及条件假设见PAPER_GUIDED_IMPLEMENTATION.md。官方导入、合成、dry-run和8秒train引擎接入通过，不能据此宣称视觉定位、真实K=2或算法性能通过。旧章节关于“当前空动作”的文字为当时历史状态。

# photo定位增量（2026-09-07）

最新定位证据见[PIXEL_LOCALIZATION_VALIDATION.md](PIXEL_LOCALIZATION_VALIDATION.md)。公开时间保持同局相对秒，不按各机reset重置原点；receipt-first-seen不是capture。Detection仍无bbox/深度/稳定像素候选字段。新的正下视、稳定直飞图像提供离线条件位置和约1.62px留出一致性，但水平/垂直FOV与有效高度不可分别确认，未知采集延迟还可造成绝对位置偏移；不能宣称在线视觉定位已通过。20003样例支持pan相对机头，但相似度不足以取代完整坐标合同。未把离线标注或拟合高度加入在线策略。

# 2026-09-07晚增量核验

早期未验证项现补充如下，细节及证据见[PERCEPTION_CONTROL_VALIDATION.md](PERCEPTION_CONTROL_VALIDATION.md)。

- 本机photo实测为JPEG 1024×768，三机各900/901拍有图；SDK的“PNG bytes”不能作为格式硬约束。无捕获时间戳，哈希变化不证明帧龄/延迟。
- train也能接收真实photo；eval只有model路径非空才启动默认YOLO。自定义sensor决定结果选用，但eval+model时默认worker仍预先启动，与SDK-API.md:173文字冲突。
- 默认YOLO单worker绑定首机；target_lat/lon由最高置信框角度和调用机当前位姿按平地近似反算，无目标ID/稳定关联；固定60/45度FOV、heading与时间同步风险仍未校准。
- 60秒探针中dt固定0.1、累加90.1秒，实际仿真59.9833秒、回调墙钟111.865秒。通信对照支持仿真时间限频，但不能精确还原C++滑窗边界；上报1Hz源自裁判sim_time差值；YOLO缓存年龄则用墙钟。
- 基本云台/FOV/速度/导航响应已观察。SDK-API.md:445–446明确云台60/30度每秒只限内部auto_track；不能将通用配置误套到point_gimbal。
- 广播正常、自消息与历史重复已处理；send_to每机12条尝试全部未在三机收件箱出现，原因待确认。sent是尝试计数，不等于送达。

---

# 赛题二 SDK 合同（本地核验）

版本：OpenSim 2.0.3 / Git `4346c8b`；正式手册V2.0.2。证据等级和冲突处置见 `ENVIRONMENT_AUDIT.md`。下列官方路径均相对 SIM_ROOT；列出源码确认、文档声明、实验观察及待确认的差别，不把Python注释当作未公开C++的实现证明。

## 1. Agent、生命周期和时间

**SDK/源码确认**：`competition.sdk.scenarios.coop_decoy.CoopAgent` 继承 core.agent.Agent，`CoopObs` 是无新增字段的 Observation 子类；运行时 isolation.build_obs 实际返回基类 Observation。推荐类型标注 Observation，不能依赖实际对象为 CoopObs。

```python
class EntryAgent(CoopAgent):
    # 继承构造器 __init__(self, my_uid: str)
    def configure(self, config): ...  # 可选，当前赛题二CLI实际给{}
    def reset(self): ...             # 清理本机实例状态
    def sensor(self, obs, dt): ...   # 可选
    def decide(self, obs, dt): ...   # 必需，返回list[Command]
```

出处：core/agent.py:19，scenarios/coop_decoy/agent.py，core/runner.py:285–299、:438–449、:551–583。runner从uav列表逐台调用 `agent_cls(my_uid=uid)`，本场景创建3个独立对象；configure后reset，赛局内不会周期性reset。三对象在同一Python进程中顺序调用，不是三个子进程；全局变量共享在技术上可能但违反信息隔离。所有可变策略状态属于 `self`。飞机被引擎标记destroyed后跳过其decide。

默认 control_rate_hz=10；runner传给sensor/decide的dt固定0.1，循环末还sleep0.1加上计算开销。不是测量的墙钟或仿真步长。评分按引擎相邻sim_time差值累计。暂停/重复帧会触发降频，前几次重复仍可能回调。

合法相对仿真秒来自 `obs.briefing.score_view.sim_time`：首个周期score_view=None；后续分数/清除数量来自上一周期，但sim_time为**本次帧时间减首帧时间**。检测没有独立时间戳；不能假定图像/检测/分数严格同一时刻。`dt`可用于控制回调计数，涉及20秒跟踪推断、通信限速、轨迹速度估计时优先用合法相对时钟并处理None、重复和倒退。出处：runner.py:484–539、:570–620。

sensor返回值（perception/resolver.py）：None＝用默认识别器；空list＝明确无检测；非空list＝采用自研输出、第0个是主检测；`SKIP_DETECTION`＝跳过检测并用空检测。sensor异常回退默认检测；decide异常记录日志且本机当拍空命令。不要用异常实现状态机。

## 2. 合法观测数据

顶层仅 `self: SelfView`、`comm_inbox: tuple[Message,...]`、`briefing: MissionBriefing`。冻结dataclass不代表嵌套dict深度不可变，不应修改观测。定义：core/observation.py:32–230；投影：core/isolation.py:72–139。

| SelfView字段 | Python类型/单位 | 缺失及语义 |
| --- | --- | --- |
| uid | str | 本机身份；不是目标身份 |
| lat, lon | float，WGS84度 | 本机经纬度 |
| alt | float，m | 文档锁500；实测约500.00005–500.00026，不能用精确相等判断。MSL/AGL及地形高程处理的完整定义未能从引擎源码确认 |
| heading_deg | float，度 | 基线按0北、顺时针正使用；边界归一化和实际引擎坐标响应待专项小实验 |
| speed | float，m/s | 本机标量速度，没有vx/vy |
| gimbal_pan, gimbal_tilt | float，度 | 原始pan_angle/tilt_angle；缺失默认0。SDK描述tilt向下负；pan相对机头/世界的资料有冲突，见命令节 |
| gimbal_fov_deg | float，度 | 优先fov，次fov_deg，缺失默认30 |
| detection | Detection | 必有占位；未检出时detected=False、confidence=0 |
| photo | bytes或None | 无UE/尚无帧/关闭时None；不是文件路径；缓存旧帧可能重复 |
| detections | tuple[Detection,...] | **仅解析结果超过1个时填入**；单检测存在时此字段仍可能为空，不可只看复数列表 |
| status | str | 默认active，可为destroyed；毁机后runner通常停止回调 |
| jammed | bool | 本机external_jammed，默认False；字段通用，不表示本赛题存在干扰 |
| comm_stats | CommStats | 所有整数缺失默认0；本机计数，实测累计而非本拍 |

Detection 完整字段（observation.py:103–117）：

| 字段 | 类型 | 约束/含义 |
| --- | --- | --- |
| detected | bool，构造必填 | 是否检出 |
| confidence | float，构造必填 | 声明0–1；训练模式由概率/距离生成，不是可靠真假概率；dataclass不自动钳位 |
| target_lat, target_lon | Optional[float]，默认None | 识别输出的含噪经纬度，非真值；detected也不能替代非None检查 |
| azimuth_error_deg | Optional[float]，默认None | 角误差度，精确正负定义未由底层证实 |
| target_type | str，默认空串 | 可能ground_vehicle等；诱饵被伪装为ground_vehicle，不能当真/假标签 |

**没有 target_id、稳定跟踪ID、目标速度、毁伤标志、bbox、目标时间戳或真值类型标志**。自研需要从合法多帧检测关联自己的临时轨迹编号；不能将裁判/场景实体ID抄入在线策略。Detection 构造实际要求confidence，不能照抄省略它的示例。

MissionBriefing（observation.py:188–213，coop_decoy/runner.py:54–72）完整字段：self_uid:str；fleet_size:int；mission_area:AreaSpec|None；known_threats:tuple[ZoneSpec,...]；params:dict；target_initial_pos:tuple[float,float]|None；target_count:int|None；approximate_zones:tuple[ApproxZoneSpec,...]；score_view:ScoreView|None。本场景fleet_size=3、target_count=3；target_initial_pos=None、known_threats和approximate_zones为空；params包含coop_k=2、sector_center_lat=27.0、sector_center_lon=125.0。不能由通用类里的target_initial_pos推断赛题二已知目标起点。

AreaSpec为lat_min/max、lon_min/max，度。本地briefing与实际地形评分边界不同，详见审计。ZoneSpec是kind、polygon（(lat,lon)点列）、alt_min/max；ApproxZoneSpec是kind、bbox（两个经纬度角点）、area_m2、alt_min/max、dynamic，属于通用字段，不向赛题二添加赛题三规则。

ScoreView字段：total_score:float、dimension_scores:tuple[(str,float),...]、passed:bool、n_destroyed:int、n_targets:int、sim_time:float（秒）。只有总体成绩与清除数量，不能知道哪辆目标被清除、剩余目标坐标、每目标跟踪时长或队友位置。

## 3. 命令签名、执行和物理限制

出处：core/commands.py:45–167。Command含verb:str、params:dict；使用公开构造器，不自行利用底层管理verb。

| 真实Python签名 | 路由/参数 | 限制依据 |
| --- | --- | --- |
| fly_to(lat, lon, alt=None, speed=None, loiter_radius=200.0, turn_direction="right") | set_destination；经纬度、米、m/s；未提供alt/speed时SDK不把这两个key写入params | SDK-API.md:392：盘旋半径非负、左右方向left/right，高度参数忽略；C++拒绝/钳位未直接验证 |
| set_heading(heading_deg) | set_heading / heading，度 | 通用约束转弯≤30度/秒，配置提供最大转弯率；尚未测定阶跃响应 |
| set_speed(speed) | set_speed / speed，m/s | 手册15–40；SDK称引擎静默钳位；配置加速度5m/s²，未用极端命令验证 |
| point_gimbal(pan_deg, tilt_deg) | component.gimbal_tracking.set_orientation / pan,tilt | SDK声明不钳位、瞬时，建议pan[-180,180]、tilt[-90,90]；通用gimbal配置仍列60/30度每秒速率，实际待确认 |
| set_gimbal_fov(fov_deg) | set_fov / angle，度 | 手册5–50，SDK声明引擎钳位；基线实际读到50；通用预设默认60/上限120不能替代比赛约束 |
| broadcast(payload: str) | comm.broadcast | Python构造时检查UTF-8字节≤50；后续引擎限频 |
| send_to(peer_uid: str, payload: str) | comm.send / peer_target_unique_id,payload | 同字节限制；目标是队友uid，不是目标ID |
| report_target(lat, lon, target_id=None) | agent.report | 仅裁判处理，不发引擎，不占50字节通信payload；target_id为可选选手标签，不决定裁判目标匹配 |

普通构造器主要转换float，不完整验证范围、有限值或枚举。SimClient.publish强制unique_id为当前Agent.my_uid再JSON序列化（core/client.py:98–107）；Python侧没有完整命令白名单/schema校验。发行包 sim-commands.schema 较旧，不能用它否定SDK暴露的comm等命令，也不能认为任意自造verb合法。

同周期：依Agent顺序收集，依返回list顺序发布；可同时导航、云台、FOV、通信、上报。普通同类多条的最终物理效果由未发行引擎实现决定，**未确认一律“最后生效”**。report有明确特例：同机同拍只取最后一条（core/runner.py:691–704）。控制意图保留至后续命令/导航终态，空命令不会使固定翼悬停；目标点导航进入盘旋。各verb持久状态与互相覆盖的细节仍应做最小物理试验。

坐标风险：基线bearing使用0北顺时针，瞄准时用bearing-heading作pan；`perception/bbox_to_latlon.py` 却没有heading输入、用pan作地理方位。基线_search_alt=200而手册锁500，影响它计算tilt。两者不能作为统一坐标合同直接复制。后续用合法自机姿态/图像和单一受控指令核验角度，不读全局真值控制。

## 4. 通信合同与实测

Message三个字段：sender_uid:str、payload:str、recv_time:float。无发送者坐标、消息ID、队友全列表；坐标/角色/序号需自己在payload编码。UTF-8长度在 `_check_payload` 计算，不含外层JSON转义和协议头；50个ASCII字符通过，16个“中”+2个ASCII通过，17个“中”=51字节抛PayloadTooLarge（项目check探针）。dict、原始bytes不是本接口payload类型；自行编码为字符串并检查字节数。

**手册明确/配置确认**：4Hz、50字节；赛题二通信不限距离（defaults comm.range=1e8m等效覆盖地图），队列容量32；commands.py旧注释约1000m与当前SDK-API.md:407及配置不一致。频率限制位于引擎，SDK不自动节流，滑窗长度边界、发送/广播是否共享计数、非法目标、队列溢出规则的底层源码不可见，未做极限试验。

**真实引擎观察**：基线运行中只读采样98帧，`comm-observations.json` 保存汇总：各机收件箱32条，跨帧同一sender/payload/recv_time多次出现，广播含本机sender，stats随运行累计增长。`isolation.py:105–121` 原样投影整个inbox，不清空、不去重。`recv_time`本次为相对仿真秒，原始world sim_time则以-28800起算；不能直接将二者相减。未把此广播试验扩大解释为定向发送所有边界都已验证。

CommStats全部字段：sent、delivered、received、rejected_bytes、rejected_rate、rejected_range、rejected_jam。计数如何逐项定义/重置待边界试验；已知需要跨帧差分而不是每拍相加。第一阶段接收应按sender+协议序号去重、设置过期时间、显式处理自消息；缓存仅存在实例self内。实验读取Redis仅用于离线审计，在线模块不包含Redis依赖。

## 5. K=2跟踪与官方评分

执行的裁判是 `competition/sdk/_vendored/coop_eval.py`，由core/scoring.py转导出。profile_multi_uav_coop_decoy在:285–307，赛题runner显式K=2，600秒（profile函数自身默认duration120不是CLI实际值）。

1. **几何判定**：core/runner.py:651开始，`_vendored/uav_target_map.py` 用引擎gimbal detection和目标坐标匹配最近真车/诱饵，120m匹配门限，排除已毁无人机。裁判用全状态，Agent看不到这些内部目标ID。自研sensor置信度/输出坐标不是直接积累几何锁定的输入。
2. **清除**：同一真目标至少2架同时有效检测，累计20秒；无需固定同一对飞机，只看人数。失去K条件后≤2秒恢复可回补，中断>2秒清零；跟踪按相邻原始仿真时间差累计，非控制dt。已清除不可逆，runner对真车内部set_position令其停车（:778–811）；诱饵不因该逻辑停车。Agent无attack命令，无每目标清除标志，停车只能作为含不确定性的行为证据。源码:399–510；手册B0140。
3. **上报匹配**：取每机每拍最后一次report，匹配最近存活真目标，无额外距离门限。若某个已清除真目标更近（严格dead_d<live_d）则丢弃；若无存活真目标也丢弃。target_id标签不参与分桶，不能伪造ID绕限速。每个裁判目标在所有飞机之间共享每1秒一条配额，按照runner处理顺序先接受的报告占配额。匹配使用同帧真值；先observe清除再record_report，清除当拍的报告可能已被丢弃。源码:577–628、runner.py:691–714；手册B0141。
4. **目标精度**：对每个真目标分别RMSE，再平均 `max(0, 1 - RMSE_i/120)`；未上报目标该项0，清除后冻结此前累积。JSON的总体targeting_rmse_m是诊断汇总，不能直接代入代替逐目标评分。
5. **分数**：base=0.5×kill+0.3×accuracy+0.2×mission_time，各维度0–100。kill=100×清除数/3；全歼相对240秒内time满分、240–420线性降到0，未全歼0（正式手册）。本地time原点缺陷见审计，不能利用该缺陷制定策略。
6. **惩罚**：本地源码以进入事件计数：水平机间距<200m每对、距地形矩形外缘>500m每机；持续违规不重复加，离开再入会增加。每次2分、合计封15，total=clamp(base-penalty,0,100)。手册持续/距离加重描述与此冲突。边界来自config/terrain_bbox.json，与briefing不同。出处:521–555、:798–806。
7. **passed**：本地用惩罚前base≥70且completion≥2/3判断（:809–818）；它不是“进程成功”也不是正式晋级承诺。清除诱饵不构成本赛题独立得分；旧misid状态机仍运行但不在权重中，错误报告会污染RMSE、错误跟踪浪费时间。

## 6. 感知模式和图像的信息边界

train默认 AccuracySimulator，accuracy=.85、noise_sigma_m=50；CLI约束accuracy≤.9、noise≥30。原场景Snow_Light，天气乘子(.85,1.5)，本次最高基础检出概率 .7225，位置每轴高斯sigma75m；水平距离≤1000m不衰减、1000–3000m线降，≥3000m检出率0。几何层还有SDK文档描述的斜距3000m门限，未直接读取C++验证。出处：core/perception/default_detectors.py:21–110，scenario.json:612，core/runner.py:235。

训练感知的模拟不属于“大规模训练”；本轮没有训练任何模型。正seed未传给AccuracySimulator，诱饵路线也另用未种子化随机，不能保证同seed感知/成绩一致。官方baseline真实引擎train回合仍是本地训练感知模式成绩，不是UE/YOLO或正式服务器成绩。

UE增强版有合法 `obs.self.photo` 通道：PhotoCache按本机uid拉取sync_camera bytes，约30Hz轮询，未提供图像时间戳/格式校验/失效TTL；没有新图保留旧图。SDK称PNG，UE配置保存图片格式写jpeg且save_image关闭，该配置不能证明Redis传输格式。目录里的截图、UE输出、前端总态势都不属于合法在线观测。

eval默认YoloDetector在core/runner.py:260处只绑定首个UAV，多机检测需特别核验；SDK已有此限制说明。UE config的3机容量不证明三路帧正确分配。本轮没启动UE、没下载YOLO权重、没调用eval，故**合法图像字段已确认，真实图像可达性、格式、新鲜度、三机归属以及视觉评测尚未验证**。

## 7. 加载、输出、提交

合法自研入口 `--agent zqhj_entry:EntryAgent`，模块通过项目启动器PYTHONPATH注入，不更改competition。真实命令和cwd见每次run.json。loader本身未严格验证issubclass，项目check另做继承验证；dry-run仅1个合成UAV，三实例创建只在导入探针和真实官方基线中另行验证。

官方输出 `*.evaluation.json` 包含profile、scenario、K、dwell_target_s、grace_s、total_score、base_score、dimension_scores、penalty/penalty_breakdown、passed、completion_rate、n_destroyed/n_targets、per_target、per_decoy、mission_done_time_s、n_reports、targeting_rmse_m、tick_count、score_timeline等。per_target包含destroyed、destroyed_at_s、dwell_accumulated_s、resets、coop_ticks，**没有逐目标报告数或RMSE**；这些分桶只存在裁判内部，不能从已输出的总体RMSE反推出。per_target及底层几何信息只准离线评测诊断，不能读文件回灌在线Agent。score_timeline.sim_time是相对秒，per_target.destroyed_at_s仍可能是原始时间。

手册B0129要求最终单模块Agent文件，继承赛道基类并附依赖/技术说明；本轮只建立单文件空动作入口，不宣称已完成正式提交。后续多模块开发必须保留单模块导出、干净导入环境及真实回合回归验收，确认主办方实际提交加载命令后再交付。
