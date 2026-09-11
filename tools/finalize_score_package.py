"""Attach a completed evaluation and documentation without changing tested code."""
import argparse,json,hashlib,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True);p.add_argument('--run',type=Path,required=True);a=p.parse_args()
package=a.package.resolve();run=a.run.resolve()
assert package.is_relative_to(root/'artifacts/submission') and run.is_relative_to(root/'artifacts/vision/runs')
record=json.loads((run/'run.json').read_text());assert record['status']=='completed'
manifest=json.loads((package/'manifest.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(package/'agent.py')==manifest['agent_sha256']
assert sha(package/'vision.pt')==manifest['vision_sha256']
call=json.loads((run/'runner-call.json').read_text(encoding='utf-8'))
assert call['controller_sha256']==manifest['agent_sha256'] and call['weights_sha256']==manifest['vision_sha256']
shutil.copy2(root/'docs/TECHNICAL_REPORT.md',package/'technical_report.md')
shutil.copy2(root/'SCORE_OPTIMIZATION.md',package/'SCORE_OPTIMIZATION.md')
shutil.copy2(root/'FIRST_SCORE.md',package/'FIRST_SCORE.md')
evaluation=next((run/'official').glob('*.evaluation.json'))
score=json.loads(evaluation.read_text(encoding='utf-8'))
shutil.copy2(evaluation,package/'baseline_evaluation.json')
manifest.update(technical_report_sha256=sha(package/'technical_report.md'),
    evaluation_sha256=sha(package/'baseline_evaluation.json'),evaluation_source=str(evaluation),
    validation=dict(duration_s=record['duration_sim_s'],last_sim_s=record['last_sim_s'],
        scores={k:score[k] for k in ('total_score','n_destroyed','n_reports','penalty','passed')}))
(package/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(package/'README.md').write_text(f'# {package.name} 实验包\n\nagent.py、vision.pt与本次正式回合的代码/权重哈希一致。请求时长{record["duration_sim_s"]:g}秒，实际结束于{record["last_sim_s"]:.3f}秒。官方分数{score["total_score"]:g}，清除{score["n_destroyed"]}/{score["n_targets"]}，上报{score["n_reports"]}，惩罚{score["penalty"]:g}。\n\n官方原始结果见baseline_evaluation.json；训练与推理命令见FIRST_SCORE.md。单次实验不能证明稳定高分。在线不读取裁判真值，判定补录工具不在提交包中。\n',encoding='utf-8')
print(package)
