"""Offline, fixed-protocol baseline evaluation. Never imported by an Agent."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import threading
import time

PROJECT = Path(__file__).resolve().parents[1]


def save(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim-root', type=Path, default=PROJECT.parent)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    parser.add_argument('--port-base', type=int, default=6391)
    args = parser.parse_args()
    root = args.sim_root.resolve()
    out = args.output if args.output.is_absolute() else PROJECT / args.output
    out = out.resolve()
    if not out.is_relative_to(PROJECT) or out == PROJECT or out.exists():
        parser.error('output must be a new directory inside ZqhjGame')
    for port in range(args.port_base, args.port_base + args.workers):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    manifest = json.loads((PROJECT / 'docs/release_manifest.json').read_text(encoding='utf-8'))
    before = {f['path']: digest(root / f['path']) for f in manifest['files']}
    mismatches = [f['path'] for f in manifest['files'] if before[f['path']] != f['sha256']]
    if mismatches:
        parser.error('release files changed since audit: ' + repr(mismatches))
    out.mkdir(parents=True)
    seeds = list(range(42, 52)) + [42, 42]
    lock = threading.Lock()
    state = {
        'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running',
        'argv': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()), 'sim_root': str(root),
        'supervisor_pid': os.getpid(), 'workers': args.workers, 'seeds': seeds,
        'protocol': '12 prespecified full 600s train rounds: seeds 42..51, then two repeats of 42; unchanged official baseline/default perception/weather/physics; no UE; no parameter tuning or score-based stopping.',
        'interpretation': 'Local training reference scores, not official validation-set or visual inference results. Seed does not fix all randomness. Concurrent wall-clock scheduling is a limitation.',
        'source_sha256_before': before, 'runs': [],
    }
    save(out / 'batch.json', state)

    def run_one(index, seed, lane):
        import redis
        run_out = out / f'{index + 1:02d}-seed{seed}'
        port = args.port_base + lane
        cmd = [sys.executable, '-B', '-u', '-X', 'utf8', str(PROJECT / 'tools/run_competition.py'),
               'baseline', '--sim-root', str(root), '--seed', str(seed),
               '--redis-port', str(port), '--output', str(run_out)]
        record = {'index': index + 1, 'seed': seed, 'lane': lane, 'port': port,
                  'argv': cmd, 'cwd': str(root), 'output': str(run_out), 'status': 'starting'}
        with lock:
            state['runs'].append(record)
            save(out / 'batch.json', state)
        start = time.monotonic()
        latest = None
        last_record = 0.0
        sub = None
        client = None
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        with (out / f'{index + 1:02d}-launcher.log').open('wb') as log:
            proc = subprocess.Popen(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            record.update(pid=proc.pid, status='running')
            try:
                while proc.poll() is None:
                    # Judge output for offline monitoring only. No sim:state/photo reads,
                    # no score data is sent to any Agent or command channel.
                    try:
                        if sub is None:
                            client = redis.Redis(host='127.0.0.1', port=port, socket_connect_timeout=.3, socket_timeout=.3)
                            sub = client.pubsub(ignore_subscribe_messages=True)
                            sub.subscribe('sim:score')
                        message = sub.get_message(timeout=.2)
                        if message and message['type'] == 'message':
                            value = json.loads(message['data'])
                            latest = {k: value.get(k) for k in ('sim_time', 'tick', 'final', 'total_score', 'n_destroyed', 'n_reports')}
                    except (redis.RedisError, ValueError):
                        if sub is not None:
                            sub.close()
                        if client is not None:
                            client.close()
                        sub = None
                        time.sleep(.3)
                    elapsed = time.monotonic() - start
                    if elapsed - last_record >= 10:
                        record.update(elapsed_wall_s=round(elapsed, 2), latest_official_score=latest)
                        with lock:
                            save(out / 'batch.json', state)
                        last_record = elapsed
                    if elapsed > 3600:
                        result = subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                                capture_output=True, text=True, errors='replace')
                        record['timeout_cleanup'] = {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
                        proc.wait(timeout=15)
                        break
            finally:
                if sub is not None:
                    sub.close()
                if client is not None:
                    client.close()
        record.update(exit_code=proc.returncode, elapsed_wall_s=round(time.monotonic()-start, 3))
        run_meta_path = run_out / 'run.json'
        meta = json.loads(run_meta_path.read_text(encoding='utf-8')) if run_meta_path.exists() else {}
        record['status'] = 'completed' if proc.returncode == 0 and meta.get('status') == 'completed' else 'failed'
        record['last_score_sim_seconds'] = meta.get('last_score_sim_seconds')
        record['result'] = meta.get('official_result')
        record['error'] = meta.get('error')
        record['evaluations'] = [{'path': str(run_out / p), 'sha256': digest(run_out / p)} for p in meta.get('evaluation_files', [])]
        with lock:
            save(out / 'batch.json', state)
            print(json.dumps(record, ensure_ascii=False), flush=True)
        return record['status'] == 'completed'

    def lane_work(lane):
        for index in range(lane, len(seeds), args.workers):
            if (out / 'STOP_AFTER_CURRENT').exists():
                break
            if not run_one(index, seeds[index], lane):
                # Infrastructure failure stops this lane; failures remain in denominator.
                break

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(lane_work, lane) for lane in range(args.workers)]
        errors = []
        for future in futures:
            try:
                future.result()
            except Exception as exc:
                errors.append(repr(exc))
    state['errors'] = errors
    state['source_sha256_after'] = {p: digest(root / p) for p in before}
    state['official_files_unchanged'] = state['source_sha256_after'] == before
    completed = sorted((r for r in state['runs'] if r['status'] == 'completed'), key=lambda r: r['index'])
    state['status'] = 'completed' if len(completed) == len(seeds) and not errors and state['official_files_unchanged'] else 'incomplete'
    state['finished_utc'] = datetime.now(timezone.utc).isoformat()
    for name, selected in [('distinct_seeds', [r for r in completed if r['index'] <= 10]),
                           ('seed42_repeats', [r for r in completed if r['seed'] == 42])]:
        scores = [r['result']['total_score'] for r in selected]
        state[name] = {'n': len(scores), 'scores': scores, 'mean': statistics.mean(scores) if scores else None,
                       'median': statistics.median(scores) if scores else None,
                       'sample_stddev': statistics.stdev(scores) if len(scores) > 1 else None,
                       'min': min(scores) if scores else None, 'max': max(scores) if scores else None,
                       'passed': sum(bool(r['result']['passed']) for r in selected),
                       'any_destroyed': sum(r['result']['n_destroyed'] > 0 for r in selected)}
    save(out / 'batch.json', state)
    print('BATCH_STATUS=' + state['status'], flush=True)
    return 0 if state['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
