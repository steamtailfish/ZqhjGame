# 当前资产与冻结基线清单

更新日期：2026-09-12。当前交接范围为 capture-v26、冻结 score-v22 基线、appearance-v3 训练数据及依赖图片、必要实测记录和技术文档，`artifacts/` 统一使用 Git LFS。官方 SDK/UE 发行包、本机虚拟环境和本机旧实验归档不上传。旧 Word 是 v22 技术快照，不代表 v26 当前方法或结果。

## 下载与检查

先安装 Git LFS，在官方发行包目录下首次克隆：

```powershell
git lfs install
git clone https://github.com/steamtailfish/ZqhjGame.git ZqhjGame
Set-Location ZqhjGame
git lfs pull
```

已经克隆的队友在仓库根目录执行 `git pull --ff-only`、`git lfs install --local`、`git lfs pull`。若权重或照片文件只有几行且以 `version https://git-lfs.github.com/spec/v1` 开头，那只是指针，需要完成 LFS 下载。

v22 基线及训练依赖的文件列表和 SHA256 记录在 [V22_ASSETS.json](V22_ASSETS.json)，在准备好 Python 后校验：

```powershell
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/check_v22_assets.py
```

该检查不启动比赛，不加载模型；仅验证清单内 v22 基线及依赖资产的内容、体积和哈希，**不覆盖新增 v26 文件**。v26 关键哈希见下方，并通过 `tools/check_visual_package.py` 检查独立包。下载失败时检查 Git LFS 输出，不修改 manifest 绕过错误。

## 保留范围

| 用途 | 当前路径 |
| --- | --- |
| 当前推荐运行包 | `artifacts/submission/capture-v26/`，含 `agent.py`、`vision.pt`、manifest、依赖与技术说明 |
| 冻结回归基线 | `artifacts/submission/score-v22/` 全部 9 个文件；压缩副本 `artifacts/submission/first-score-v22.zip` |
| 当前权重与训练记录 | `artifacts/vision/models/appearance-v3/appearance.pt`、`training.json` |
| 审核训练数据 | `artifacts/vision/datasets/appearance-data-v3/accepted.jsonl`，以及所有 image / source_photo 依赖图片 |
| 当前完整正式回合 | `artifacts/vision/runs/capture-v26-seed101/`，600 秒请求 / 599.9667 秒记录，18.67 分、4 报告、0 清除、0 惩罚 |
| 基线完整正式回合 | `artifacts/vision/runs/score600-v22-seed101/`，含公开观测、照片、动作和 9.06 分官方结果 |
| 当前验证与诊断 | `artifacts/checks/capture-v26-isolated.json`、`capture-v26-101-analysis.json`、`capture-v26-101-capture-analysis.json`、`capture-v26-review-01.jpg`、`capture-v26-replay.html` 等；另保留必要基线与旧实验摘要 |
| 当前协同说明 | [COOPERATIVE_CAPTURE.md](COOPERATIVE_CAPTURE.md)，当前状态见 [STATUS.md](../STATUS.md) |
| v22 技术报告快照 | `artifacts/reports/v22-technical/ZqhjGame_v22_技术报告.docx`，Markdown 快照见 [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md)，本轮不改写旧报告 |
| 参考资料 | `artifacts/papers/` 中论文阅读笔记和图示 |

部分当前训练图片位于带 v1/v2 名称的目录，这是 appearance-v3 的依赖，不是保留旧算法版本。不要再次按目录名删除。固定隔离照片也已保留：`artifacts/vision/fixtures/true-v2/observations/20002/62c13d88321f8e68637990aca8d0ec440b10194091b18397110322f876452299.image`。

当前活动资产保留 capture-v26、score-v22 回归基线和 appearance-v3 依赖。被替代的 v25 包、完整回合和原始外部跟踪文件移入本机 `.local-archive/capture-development/` 可恢复归档；其原始评分副本 `artifacts/checks/capture-v25-evaluation.json`、包来源记录 `capture-v25-package.json` 和诊断摘要保留。更早实验位于 `.local-archive/pre-v22-20260911/` 或 capture-development 归档。整个 `.local-archive/` 被 Git 忽略，不上传，不重写既有 Git 提交历史。

## v26 关键哈希

本轮原始评分文件为 `artifacts/vision/runs/capture-v26-seed101/official/coop_decoy_1789219639.evaluation.json`。代码、权重和评分分别校验：

| 文件 | SHA256 |
| --- | --- |
| `artifacts/submission/capture-v26/agent.py` | `92c4f8e7fdde358742dc7c558ee502afd124f87a37f7f7367f1739c58ae2b75f` |
| `artifacts/submission/capture-v26/vision.pt` | `819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf` |
| v26 原始 `coop_decoy_1789219639.evaluation.json` | `f75cf3973b0568cd3e1990ef86b465b3c799a93c5b8efd8db7172a9c7de8e285` |

v26 权重与 v22 相同；本轮只改进已确认任务的世界视线云台控制，没有重新训练。18.67 分来自坐标精度，官方仍为 `passed=false`、0 清除；有效协同帧不能当作连续 20 秒捕获。单 seed 结果不证明稳定高分。

## v22 冻结包关键哈希

| 文件 | SHA256 |
| --- | --- |
| `agent.py` | `202cbadb96e2cb6b39903bc49de94f2af3aaa946a111fcbad1a38860af2e7cf7` |
| `vision.pt` | `819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf` |
| `baseline_evaluation.json` | `c86139edcc5623cd04b1246d36eb4c1bddce6e3d19cb93673020355a92df0159` |

冻结 v22 保持原样，附带文档是当时快照；当前使用步骤以 QUICKSTART 为准，代码、权重和原始结果字节不变。已评估的 v26 代码和权重也不覆盖，下一轮修改必须导出到新目录。

## 训练数据路径迁移

现有 `accepted.jsonl` 的 `image` 字段混有开发机绝对路径（前缀为 `D:/catkin_ws/hf2026-sim-windows/ZqhjGame/`）和 `ZqhjGame/artifacts/...` 相对路径。`train_vehicle_appearance.py` 直接读这个字段，不会自动改成本机目录。建议发送方同步每条记录的图片并保留其相对 `ZqhjGame` 的目录结构。

下面命令在新机器仓库根目录执行，先验证所有训练图片存在且 SHA256 匹配，再生成新的 `accepted-local.jsonl`；不覆盖原审核文件，不改变类别、框、划分或审核结论。`source_photo` 等原始来源字段保留原机路径作为历史出处；如果以后执行依赖源照片的工具，还需同步源照片并单独迁移相应字段。

```powershell
@'
from pathlib import Path
import hashlib, json

root = Path.cwd().resolve()
assert (root / 'tools/train_vehicle_appearance.py').is_file(), '请在 ZqhjGame 根目录执行'
source = root / 'artifacts/vision/datasets/appearance-data-v3/accepted.jsonl'
target = source.with_name('accepted-local.jsonl')
assert not target.exists(), '目标已存在，请检查它而不是覆盖'
old_prefix = 'D:/catkin_ws/hf2026-sim-windows/ZqhjGame/'
rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines() if line.strip()]
for row in rows:
    old = row['image'].replace('\\', '/')
    if old.startswith(old_prefix):
        relative = old[len(old_prefix):]
    elif old.startswith('ZqhjGame/artifacts/'):
        relative = old[len('ZqhjGame/'):]
    elif old.startswith('artifacts/'):
        relative = old
    else:
        raise ValueError(f'未知来源路径，需要人工核对: {old}')
    image = (root / relative).resolve()
    assert image.is_relative_to(root / 'artifacts'), image
    assert image.is_file(), f'图片未同步: {image}'
    assert hashlib.sha256(image.read_bytes()).hexdigest() == row['sha256'], f'图片哈希不匹配: {image}'
    assert row['review_status'] == 'accepted', '含未审核样本'
    row['image'] = str(image)
with target.open('x', encoding='utf-8', newline='\n') as stream:
    for row in rows:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
print(f'已核验 {len(rows)} 条记录并写入 {target}')
'@ | .\.venv-learning\Scripts\python.exe -B -X utf8 -
```

`accepted-local.jsonl` 的文件哈希因路径变化而不同，应记录其来源为原始审核文件的迁移副本。图片内容哈希不应变化。若验证失败，先补齐图片或核对路径，不去掉哈希校验继续训练。


## 记录路径与权限

正式运行 JSON 保留原机绝对路径作为原始证据，不改写冻结记录。官方 evaluation 可直接查看；分析工具若无法找到旧提交路径，可能使用默认分析门限，因此新机器分析时要注明路径迁移影响。新的回合会记录新路径。

外部裁判诊断只用于赛后解释，不允许进入 Agent 在线输入或身份训练标签。审核记录迁移副本 `accepted-local.jsonl` 由各机器生成并被 Git 忽略。
