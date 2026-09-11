# 资产交接清单

更新日期：2026-09-11。Git 只保存代码和文档；`.gitignore` 忽略 `artifacts/`、`.venv/` 和 `.venv-learning/`。下面是开发机已有资产的路径清单，**不是 GitHub 已提供的下载链接**。当前没有自动下载入口，需要项目持有人向队友另行同步所需文件。

除官方发行包外，下列路径均相对 `ZqhjGame/`。只同步必要的资产，不要直接把整个 `artifacts/` 强制加入 Git：其中还有大量历史实验、受控数据和外部诊断记录。

## 按用途准备

| 用途 | 必需资产 | 备注 |
| --- | --- | --- |
| 运行冻结 v22 | 完整官方 Windows UE 发行包；`artifacts/submission/score-v22/` 整个目录 | 无需训练数据或旧 YOPO 控制权重；官方环境在本仓库父目录 |
| 传输冻结包 | `artifacts/submission/first-score-v22.zip` | 已有压缩副本，解压后确保 `agent.py`、`vision.pt` 等直接位于 `artifacts/submission/score-v22/`，不要多嵌套一层 |
| 修改源码再导出 | 冻结包中的 `agent.py`、`vision.pt` | QUICKSTART 显式用冻结 `agent.py` 作为 `--controller` 来源；不依赖导出器默认的历史路径 |
| 隔离模型检查 | `artifacts/vision/fixtures/true-v2/observations/20002/62c13d88321f8e68637990aca8d0ec440b10194091b18397110322f876452299.image` | `check_visual_package.py` 固定读取的受控照片；内容 SHA256 即文件名，不包含在提交 zip 内 |
| 重新训练 | `artifacts/vision/datasets/appearance-data-v3/accepted.jsonl` 及每行 `image` 引用的全部图片 | 单独复制 JSONL 不够；需迁移绝对路径，见下节 |
| 核查训练依据 | `artifacts/vision/models/appearance-v3/training.json`、审核记录及原始受控照片 | `appearance.pt` 与冻结 `vision.pt` 哈希相同；源照片路径保留审核来源 |
| 原始实验分析 | `artifacts/vision/runs/score600-v22-seed101/` 整个目录 | 包含官方结果、公开图像、控制记录；仅复制 evaluation 不能运行完整分析工具 |
| 已有诊断结论 | `artifacts/checks/score-v22-101-analysis.json`、`score-v22-isolated.json`、`score-v22-release-integrity.json` | 已有检查记录，与正式评分作用不同 |
| 技术 Word | `artifacts/reports/v22-technical/ZqhjGame_v22_技术报告.docx` | 8 页报告，亦被 artifacts 规则忽略；本次 Git 交接不包含该二进制文档 |
| 历史引导学习研究 | `artifacts/submission/competition-guidance-v3.py` 及对应训练数据/模型 | 仅研究旧分支时需要，不是运行冻结 v22 的前提 |

## 冻结包核验

冻结目录有 9 个文件：`agent.py`、`vision.pt`、`requirements.txt`、`technical_report.md`、`manifest.json`、`README.md`、`FIRST_SCORE.md`、`SCORE_OPTIMIZATION.md`、`baseline_evaluation.json`。保持目录原样。当前 Git 提交号标记源码版本，以下哈希标记真正运行过的独立提交资产。

| 文件 | SHA256 |
| --- | --- |
| `agent.py` | `202cbadb96e2cb6b39903bc49de94f2af3aaa946a111fcbad1a38860af2e7cf7` |
| `vision.pt` | `819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf` |
| `baseline_evaluation.json` | `c86139edcc5623cd04b1246d36eb4c1bddce6e3d19cb93673020355a92df0159` |

在仓库根目录执行以下 PowerShell。结果不匹配就重新核对传输来源，不修改包的哈希或覆盖模型以绕过错误。

```powershell
$expected = @{
  'agent.py' = '202cbadb96e2cb6b39903bc49de94f2af3aaa946a111fcbad1a38860af2e7cf7'
  'vision.pt' = '819381fa5b383310592238f0cc61843c5ac808228bc4ec9d997295c9c822a0cf'
  'baseline_evaluation.json' = 'c86139edcc5623cd04b1246d36eb4c1bddce6e3d19cb93673020355a92df0159'
}
foreach ($name in $expected.Keys) {
  $actual = (Get-FileHash -LiteralPath "artifacts/submission/score-v22/$name" -Algorithm SHA256).Hash
  if ($actual -ne $expected[$name]) { throw "资产哈希不匹配：$name" }
  Write-Output "OK $name"
}
```

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

## 历史记录的迁移边界

部分实验 JSON 也保存原机绝对路径。可直接查看复制来的官方 evaluation，但完整分析工具可能无法按旧路径读取提交模块，或退回默认分析门限；不能把迁移后的诊断字段当作同配置结果。建议保留原始记录不改，必要时另建有来源说明的分析副本；新回合自然会记录新机器路径。

官方引擎、SDK 和 UE 从队伍获准使用的官方发行包取得。外部裁判诊断记录只用于赛后解释，不允许进入 Agent 在线输入或身份训练标签。
