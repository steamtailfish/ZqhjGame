"""Summarize unmodified official evaluation files; offline only."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    args = parser.parse_args()
    folder = args.batch.resolve()
    project = Path(__file__).resolve().parents[1]
    if not folder.is_relative_to(project):
        parser.error('batch must be inside ZqhjGame')
    batch = json.loads((folder / 'batch.json').read_text(encoding='utf-8'))
    rows = []
    details = []
    for run in sorted(batch['runs'], key=lambda r: r['index']):
        run_dir = Path(run['output'])
        meta_file = run_dir / 'run.json'
        meta = json.loads(meta_file.read_text(encoding='utf-8')) if meta_file.exists() else {}
        paths = list((run_dir / 'official').glob('*.evaluation.json'))
        evaluation = json.loads(paths[0].read_text(encoding='utf-8')) if len(paths) == 1 else {}
        log_file = run_dir / 'console.log'
        log = log_file.read_text(encoding='utf-8', errors='replace') if log_file.exists() else ''
        errors = [line for line in log.splitlines() if any(s in line for s in (
            'decide() error:', 'Traceback (most recent call last)', 'prepare_scenario failed:',
            'engine start failed:', 'No sim:state', 'exited immediately'))]
        timeline = evaluation.get('score_timeline', [])
        times = [row['sim_time'] for row in timeline]
        last = max(times, default=0)
        monotonic = all(b >= a for a, b in zip(times, times[1:]))
        checks = {
            'launcher_completed': meta.get('status') == 'completed' and meta.get('exit_code') == 0,
            'official_cli_exit_zero': meta.get('cli_exit_code') == 0,
            'one_raw_evaluation': len(paths) == 1,
            'profile_coop_decoy': evaluation.get('profile') == 'multi_uav_coop_decoy',
            'K2_20s_grace2s': (evaluation.get('K'), evaluation.get('dwell_target_s'), evaluation.get('grace_s')) == (2, 20.0, 2.0),
            'three_targets': evaluation.get('n_targets') == 3,
            'three_agents': '3 agent(s) instantiated' in log,
            '18_vehicle_navigation_ok': '[INJECT] 完成: ok=18 fail=0' in log,
            'requested600s_completed': meta.get('requested_sim_seconds') == 600 and 599 <= last <= 601,
            'timeline_monotonic': monotonic,
            'no_known_runtime_errors': not errors,
        }
        result_status = 'valid_full_round' if all(checks.values()) else ('interrupted_by_user' if run['status'] == 'stopped_by_user' else 'pending' if run['status'] in ('starting', 'running') else 'invalid')
        dims = evaluation.get('dimension_scores', {})
        per_target = evaluation.get('per_target', {})
        penalty = evaluation.get('penalty_breakdown', {})
        row = {
            'round': run['index'], 'seed': run['seed'], 'lane': run['lane'], 'status': result_status,
            'total_score': evaluation.get('total_score'), 'base_score': evaluation.get('base_score'),
            'penalty': evaluation.get('penalty'), 'destroyed': evaluation.get('n_destroyed'),
            'kill': dims.get('kill'), 'accuracy': dims.get('accuracy'), 'mission_time': dims.get('mission_time'),
            'reports': evaluation.get('n_reports'), 'overall_report_rmse_m': evaluation.get('targeting_rmse_m'),
            'coop_ticks_sum': sum(t.get('coop_ticks', 0) for t in per_target.values()),
            'tracking_resets_sum': sum(t.get('resets', 0) for t in per_target.values()),
            'proximity_events': penalty.get('proximity', {}).get('count'),
            'boundary_events': penalty.get('boundary', {}).get('count'),
            'passed': evaluation.get('passed'), 'last_sim_seconds': last,
            'score_ticks': evaluation.get('tick_count'), 'elapsed_wall_seconds': meta.get('elapsed_seconds'),
            'max_timeline_gap_s': max((b-a for a,b in zip(times,times[1:])), default=None),
            'raw_evaluation': str(paths[0].relative_to(folder)) if len(paths) == 1 else None,
        }
        rows.append(row)
        details.append({'round': run['index'], 'checks': checks, 'errors': errors,
                        'per_target': per_target, 'penalty_breakdown': penalty,
                        'evaluation_sha256': hashlib.sha256(paths[0].read_bytes()).hexdigest() if len(paths) == 1 else None})
    with (folder / 'scores.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    aggregates = {}
    for name, selection in [('distinct_seeds', lambda r: r['round'] <= 10), ('seed42_repeats', lambda r: r['seed'] == 42)]:
        chosen = [r for r in rows if r['status'] == 'valid_full_round' and selection(r)]
        scores = [r['total_score'] for r in chosen]
        aggregates[name] = {'n': len(chosen), 'scores': scores,
            'mean': statistics.mean(scores) if scores else None,
            'median': statistics.median(scores) if scores else None,
            'sample_stddev': statistics.stdev(scores) if len(scores) > 1 else None,
            'min': min(scores) if scores else None, 'max': max(scores) if scores else None,
            'passed_count': sum(bool(r['passed']) for r in chosen),
            'any_destroyed_count': sum(r['destroyed'] > 0 for r in chosen)}
    summary = {'batch_status': batch['status'], 'planned_rounds': len(batch['seeds']),
               'not_started_rounds': len(batch['seeds']) - len(batch['runs']),
               'user_interrupted_rounds': sum(r['status'] == 'interrupted_by_user' for r in rows),
               'valid_full_rounds': sum(r['status'] == 'valid_full_round' for r in rows),
               'official_files_unchanged': batch.get('official_files_unchanged'),
               'aggregates': aggregates, 'rows': rows, 'verification': details}
    (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 官方原基线多回合训练参考评测', '',
        f"状态：{batch['status']}；有效完整回合 {summary['valid_full_rounds']}/{len(batch['seeds'])}。", '',
        '预先固定12轮：seed42–51各一轮，另重复seed42两轮。10个不同种子与同种子重复分别统计，不按得分筛选。',
        'OpenSim 2.0.3；每轮600仿真秒；官方CoopDistributedAgent；train/AccuracySimulator，默认accuracy=0.85、noise_sigma=50m，场景默认距离门限与天气。未启动UE/YOLO，photo=auto无渲染器，不称为正式视觉评测。',
        '4路独立Redis/引擎/输出，未改变仿真速度。并发调度及SDK未完全受seed控制的感知/诱饵随机性限制逐帧复现；不宣称统计独立或泛化能力已充分证明。', '',
        '|轮|seed|状态|总分|摧毁|精度分项|报告数|总体RMSE(m)|惩罚|末仿真秒|墙钟秒|',
        '|---|---|---|---|---|---|---|---|---|---|---|']
    def fmt(v):
        return '—' if v is None else f'{v:.3f}' if isinstance(v, float) else str(v)
    for r in rows:
        lines.append('|' + '|'.join(fmt(r[k]) for k in ('round','seed','status','total_score','destroyed','accuracy','reports','overall_report_rmse_m','penalty','last_sim_seconds','elapsed_wall_seconds')) + '|')
    lines += ['', '## 分组汇总', '', '```json', json.dumps(aggregates, ensure_ascii=False, indent=2), '```', '',
        'score/kill/accuracy/mission_time直接摘自官方evaluation；总体报告RMSE仅作诊断，不能代替裁判逐目标RMSE的均值评分。有效完整回合要求CLI退出0、600秒末帧、3机3真目标、K=2/20秒/2秒、18车导航注入成功，以及无已知回调/启动异常。', '',
        '## 依据和复现', '',
        '手册提取B0082：600秒；B0108：多seed；B0134：训练参考/验证新路线/最终客观90%+创新10%；B0140–B0147：赛题二判定与权重。手册未规定本地样本数。',
        'competition/sdk/cli.py:122–144：感知参数；sdk/core/runner.py:235–271：train/eval真实选择；sdk/_vendored/sim_runner.py:142–173：子进程启动与退出；sdk/scenarios/coop_decoy/runner.py:244：官方运行入口；baselines/coop_distributed.py:21–24：K=2协同仍为TODO。',
        'batch.json保存完整批次命令、cwd、PID、种子、分路端口与前后60文件SHA256；每轮run.json保存实际CLI、解释器、依赖版本、600秒完成证据、退出码和耗时。每轮official/*.evaluation.json是未经改写的原始官方成绩；console.log/engine.stderr.log/redis/保留原始日志。scores.csv和summary.json仅离线汇总。', '',
        '从SIM_ROOT实际执行（解释器和脚本绝对路径见batch.json）：', '```powershell',
        '& .\\python\\python.exe -B -u -X utf8 .\\ZqhjGame\\tools\\run_baseline_batch.py --output artifacts/baseline-batch/20260910-12rounds --workers 4 --port-base 6391',
        '```',
        '复跑必须换一个新的项目内输出目录。STOP_AFTER_CURRENT文件只停止后续排队回合，当前回合仍正常跑完；超时仅清理本批次持有的PID树。只订阅本批次官方sim:score作离线进度监控，绝不送入Agent。',
        '这些分数不包含现场创新性评审，不能折算为已取得的比赛总成绩。正式视觉条件/权重提交许可仍以主办方确认为准。']
    (folder / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('batch_status','planned_rounds','valid_full_rounds','aggregates')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
