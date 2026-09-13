# 当前资产与冻结基线清单

更新日期：2026-09-13。本次发布 capture-v31，保留历史发布 v26、冻结 score-v22 基线、appearance-v3 权重、审核数据与图片依赖。`artifacts/` 使用 Git LFS。官方 SDK/UE、虚拟环境和本机归档不上传。

v31 的算法、模型及原始评分字节保持冻结；发布说明与 manifest 元数据更新为本次交接状态，原本地说明已有备份。当前 `src/` 与 v31 manifest 的 17 个导出模块一致。旧 Word 保留 v22 技术快照；仓库 [TECHNICAL_REPORT](TECHNICAL_REPORT.md) 描述当前 v31。

## 下载与检查

首次克隆请在官方发行包目录执行：

```powershell
git lfs install
git clone https://github.com/steamtailfish/ZqhjGame.git ZqhjGame
Set-Location ZqhjGame
git lfs pull
```

已有仓库执行 `git pull --ff-only`、`git lfs install --local`、`git lfs pull`。若权重只有几行且以 `version https://git-lfs.github.com/spec/v1` 开头，它仍是指针。先完成下载，再核验。

[V22_ASSETS.json](V22_ASSETS.json) 覆盖 v22 基线及训练图片依赖，准备好 Python 后运行：

```powershell
.\.venv-learning\Scripts\python.exe -B -X utf8 tools/check_v22_assets.py
```

此检查不加载模型、不启动比赛，也不覆盖 v31 或 v26。当前包按下表检查 `agent.py`、`vision.pt`、`evaluation.json`；隔离推理检查及完整命令见 [QUICKSTART](QUICKSTART.md)。下载或哈希失败时先核对 LFS，不修改 manifest 绕过。

## 本次提供与本地保留范围

| 用途 | 路径与边界 |
| --- | --- |
| 当前运行包 | `artifacts/submission/capture-v31/` 的 `agent.py`、`vision.pt`、`requirements.txt`、`manifest.json`、`evaluation.json`、`LOCAL_REVIEW.md`、`technical_report.md` 七项核心文件 |
| 原始得分 | [v31 evaluation.json](../artifacts/submission/capture-v31/evaluation.json)，完整 600 秒请求 / 599.9833 秒记录，28.33 分、4 报告、RMSE 6.5411588239 米、0 捕获、0 惩罚、passed=false |
| 历史发布 | `artifacts/submission/capture-v26/`，18.67 分、4 报告、0 捕获；不改写成 v31 结果 |
| 冻结基线 | `artifacts/submission/score-v22/` 全部 9 个文件，以及 `artifacts/submission/first-score-v22.zip`；保留导出器所需函数与权重 |
| 当前训练 | `artifacts/vision/models/appearance-v3/appearance.pt`、`training.json`；审核清单 `artifacts/vision/datasets/appearance-data-v3/accepted.jsonl` 及其 image / source_photo 依赖 |
| v22 历史报告 | `artifacts/reports/v22-technical/ZqhjGame_v22_技术报告.docx` 与对应媒体，保留当时技术快照 |
| 仅本地保留 | 约 1 GB 的 `artifacts/vision/runs/capture-v31-seed101/` 原始照片和运行记录，不在本次上传范围 |

**加载 v31、查看历史官方得分、重新跑比赛均不需要旧 run。** 新比赛会生成新的公开记录和 evaluation。历史逐帧照片回放需要本地原始记录，仅凭评分文件无法重建；本次发布不把未提供的原图或分析工具作为复现前置条件。

训练图片目录中的 v1/v2 名称是 appearance-v3 的来源依赖，不应按旧名字删除。隔离检查还使用固定受控照片：`artifacts/vision/fixtures/true-v2/observations/20002/62c13d88321f8e68637990aca8d0ec440b10194091b18397110322f876452299.image`，已纳入 LFS 交接。

`.local-archive/` 保存本机历史实验，不上传，也不重写既有 Git 历史。此清单描述发布范围，不授权清理其他文件。

## v31 冻结哈希

| 文件 | SHA256 |
| --- | --- |
| `artifacts/submission/capture-v31/agent.py` | `f9ba07fe76c2740e67b3ade54ff54b2cef7a94402a1494912ad781f2338645d2` |
| `artifacts/submission/capture-v31/vision.pt` | `819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf` |
| `artifacts/submission/capture-v31/evaluation.json` | `85cefd8871f82885897cacc64440b4ab1d5fad890c4ffb0fede6d24d461bb3f6` |

模型沿用 appearance-v3，与 v22 / v26 相同。v31 没有重新训练，未启用 Nano 或 YOPO 学习评分头。28.33 分是单次最高分，不能称为已经捕获、稳定高分或满分。

## v26 历史发布哈希

| 文件 | SHA256 |
| --- | --- |
| `artifacts/submission/capture-v26/agent.py` | `92c4f8e7fdde358742dc7c558ee502afd124f87a37f7f7367f1739c58ae2b75f` |
| `artifacts/submission/capture-v26/vision.pt` | `819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf` |
| v26 原始 evaluation | `f75cf3973b0568cd3e1990ef86b465b3c799a93c5b8efd8db7172a9c7de8e285` |

v26 的 seed101 完整 600 秒请求结果为 18.67 分、4 报告、RMSE 9.6671 米、0 捕获。它修正了已确认任务世界视线云台，属于历史发布事实。

## v22 冻结哈希

| 文件 | SHA256 |
| --- | --- |
| `agent.py` | `202cbadb96e2cb6b39903bc49de94f2af3aaa946a111fcbad1a38860af2e7cf7` |
| `vision.pt` | `819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf` |
| `baseline_evaluation.json` | `c86139edcc5623cd04b1246d36eb4c1bddce6e3d19cb93673020355a92df0159` |

v22 的 9.06 分基线、训练与导出依赖保持原样。其附带文档是历史快照，当前命令以 QUICKSTART 为准。修改算法必须导出新目录，不能覆盖这三个已评估版本。

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
