"""Completed-run orbit/control-response audit using public per-agent records only."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median

from analyze_capture_approach import finite, frame_from_rows, sample, stats
from zqhj_state import valid_geo, wrap


def load_rows(path):
    data = path.read_bytes()
    rows = [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]
    times = [r.get('score_sim_s') for r in rows]
    if any(not finite(t) or t < 0 for t in times) or any(b < a for a, b in zip(times, times[1:])):
        raise ValueError('public control times must be finite, nonnegative and monotonic')
    return rows, hashlib.sha256(data).hexdigest()


def command_heading(row, frame):
    """Recover the issued bearing; it is not an observed executed heading."""
    own = row.get('own') or {}
    commands = row.get('commands') or []
    destinations = [c for c in commands if c.get('verb') == 'set_destination']
    direct = [c for c in commands if c.get('verb') == 'set_heading']
    if len(destinations)+len(direct) != 1:
        return None, None, 'no_unique_heading_command'
    if direct:
        value = (direct[0].get('params') or {}).get('heading')
        return (value % 360, None, 'set_heading') if finite(value) else (None, None, 'invalid_heading')
    p = destinations[0].get('params') or {}
    if (frame is None or not valid_geo(own.get('lat'), own.get('lon')) or
            not valid_geo(p.get('latitude'), p.get('longitude'))):
        return None, None, 'invalid_destination_or_pose'
    source = frame.xy(own['lat'], own['lon'])
    waypoint = frame.xy(p['latitude'], p['longitude'])
    dx, dy = waypoint[0]-source[0], waypoint[1]-source[1]
    distance = math.hypot(dx, dy)
    if distance < 1e-3:
        return None, distance, 'degenerate_destination'
    return math.degrees(math.atan2(dx, dy)) % 360, distance, 'set_destination'


def response(a, b, max_gap):
    """Response over the command hold until the next recorded navigation command."""
    dt = b['t']-a['t']
    if dt <= 0 or dt > max_gap:
        return dict(status='duplicate_time_or_control_gap', dt_s=dt)
    result = dict(status='sampled', dt_s=dt, from_s=a['t'], to_s=b['t'],
        actual_yaw_rate_deg_s=None, actual_acceleration_mps2=None, rate_gain=None,
        same_direction=None, radius_change_m=None, own_closing_to_previous_point_m=None,
        moving_point_contribution_m=None)
    if finite(a['own_heading_deg']) and finite(b['own_heading_deg']):
        result['actual_yaw_rate_deg_s'] = wrap(b['own_heading_deg']-a['own_heading_deg'])/dt
    if finite(a['actual_speed_mps']) and finite(b['actual_speed_mps']):
        result['actual_acceleration_mps2'] = (b['actual_speed_mps']-a['actual_speed_mps'])/dt
    requested, actual = a['requested_yaw_rate_deg_s'], result['actual_yaw_rate_deg_s']
    if finite(requested) and abs(requested) > .5 and finite(actual):
        result['rate_gain'] = actual/requested
        result['same_direction'] = requested*actual > 0
    if a['point'] is not None and a['position'] is not None and b['position'] is not None:
        frozen_distance = math.dist(b['position'], a['point'])
        result['own_closing_to_previous_point_m'] = a['range_m']-frozen_distance
        if b['range_m'] is not None and a['key'] == b['key']:
            result['radius_change_m'] = b['range_m']-a['range_m']
            result['moving_point_contribution_m'] = frozen_distance-b['range_m']
    return result


def summary(rows):
    responses = [r['response'] for r in rows if r['response']['status'] == 'sampled']
    known_ranges = [r for r in rows if finite(r['range_m'])]
    direction = [r['same_direction'] for r in responses if r['same_direction'] is not None]
    return dict(navigation_commands=len(rows),
        first_s=rows[0]['t'] if rows else None, last_s=rows[-1]['t'] if rows else None,
        known_command_hold_s=sum(r['dt_s'] for r in responses),
        response_status=Counter(r['response']['status'] for r in rows),
        roles=Counter(r['role'] for r in rows), phases=Counter(r['phase'] for r in rows),
        public_point_sources=Counter(r['source'] for r in rows),
        actual_speed_mps=stats([r['actual_speed_mps'] for r in rows]),
        requested_yaw_rate_deg_s=stats([r['requested_yaw_rate_deg_s'] for r in rows]),
        actual_yaw_rate_deg_s=stats([r['actual_yaw_rate_deg_s'] for r in responses]),
        actual_acceleration_mps2=stats([r['actual_acceleration_mps2'] for r in responses]),
        observed_over_requested_turn_rate=stats([r['rate_gain'] for r in responses]),
        significant_requested_turn_direction=dict(samples=len(direction), same=sum(direction)),
        waypoint_distance_m=stats([r['waypoint_distance_m'] for r in rows]),
        range_to_public_point_m=dict(**stats([r['range_m'] for r in rows]),
            first_sample=rows[0]['range_m'] if rows else None,
            last_sample=rows[-1]['range_m'] if rows else None,
            first_known_s=known_ranges[0]['t'] if known_ranges else None,
            last_known_s=known_ranges[-1]['t'] if known_ranges else None),
        radius_change_per_interval_m=stats([r['radius_change_m'] for r in responses]),
        own_closing_to_previous_point_m=stats([r['own_closing_to_previous_point_m'] for r in responses]),
        moving_point_contribution_m=stats([r['moving_point_contribution_m'] for r in responses]),
        planning=Counter('feasible' if r['plan_feasible'] is True else
                         'infeasible' if r['plan_feasible'] is False else 'unknown' for r in rows),
        clearance_m=stats([r['clearance_m'] for r in rows]),
        own_visual_commands=sum(r['own_visual'] is True for r in rows))


def analyze(run, command_period=.5, include_events=False):
    run = Path(run)
    manifest_path = run/'run.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != 'completed':
        raise ValueError('run must be completed before opening control events or observations')
    if not finite(command_period) or command_period <= 0:
        raise ValueError('command period must be finite and positive')
    folders = sorted(p for p in (run/'observations').iterdir() if p.is_dir())
    roster = [p.name for p in folders]
    agents = []
    for folder in folders:
        path = folder/'control-events.jsonl'
        if not path.exists():
            agents.append(dict(uid=folder.name, status='no_control_events_recorded', modes={}))
            continue
        rows, digest = load_rows(path)
        end = manifest.get('last_sim_s')
        if finite(end) and any(r['score_sim_s'] > end+1e-6 for r in rows):
            raise ValueError('control event beyond completed official ending')
        public_path = folder/'observations.jsonl'
        public_rows, public_hash = load_rows(public_path) if public_path.exists() else ([], None)
        frame = frame_from_rows(public_rows or rows)
        recorder_path = folder/'capture-recording.json'
        recording = json.loads(recorder_path.read_text(encoding='utf-8')) if recorder_path.exists() else None
        nav, radio_only = [], 0
        for row in rows:
            own = row.get('own') or {}
            if str(own.get('uid')) != folder.name:
                raise ValueError('control event own UID disagrees with its agent folder')
            s = sample(row, folder.name, roster, frame)
            if not s['new_navigation_command']:
                radio_only += 1
                continue
            c = (row.get('diagnostics') or {}).get('capture') or {}
            mode = c.get('planner_goal_mode')
            mode = mode if isinstance(mode, str) and mode else 'unknown'
            bearing, distance, command_source = command_heading(row, frame)
            heading = own.get('heading_deg') if finite(own.get('heading_deg')) else None
            requested = wrap(bearing-heading)/command_period if finite(bearing) and finite(heading) else None
            s.update(mode=mode, own_heading_deg=heading, commanded_heading_deg=bearing,
                     waypoint_distance_m=distance, heading_command_source=command_source,
                     requested_yaw_rate_deg_s=requested)
            nav.append(s)
        intervals = [b['t']-a['t'] for a, b in zip(nav, nav[1:]) if b['t'] > a['t']]
        cadence = median(intervals) if intervals else None
        max_gap = min(1., 2*cadence) if cadence else 1.
        for i, s in enumerate(nav):
            s['response'] = response(s, nav[i+1], max_gap) if i+1 < len(nav) else dict(status='no_next_navigation_sample')
        groups = {}
        for s in nav:
            groups.setdefault(s['mode'], []).append(s)
        segments, current = [], []
        for s in nav:
            same = (current and s['mode'] == 'orbit_arc' and s['key'] == current[-1]['key']
                    and s['role'] == current[-1]['role'] and s['partner'] == current[-1]['partner']
                    and 0 < s['t']-current[-1]['t'] <= max_gap)
            if current and not same:
                segments.append(current)
                current = []
            if s['mode'] == 'orbit_arc':
                current.append(s)
        if current:
            segments.append(current)
        episodes = []
        for segment in segments:
            s = segment[0]
            item = dict(owner=s['key'][0] if s['key'] else None,
                        mission=s['key'][1] if s['key'] else None, role=s['role'], partner=s['partner'],
                        sample_span_s=segment[-1]['t']-s['t'], **summary(segment))
            if include_events:
                item['events'] = segment
            episodes.append(item)
        agents.append(dict(uid=folder.name, status='analyzed', control_events_sha256=digest,
            public_observations_sha256=public_hash, all_nonempty_control_events=len(rows),
            non_navigation_events=radio_only, navigation_events=len(nav),
            median_navigation_interval_s=cadence, max_response_gap_s=max_gap,
            recorder_dropped=recording.get('dropped') if recording else None,
            wrapper_dropped=recording.get('wrapper_dropped') if recording else None,
            modes={mode:summary(items) for mode,items in groups.items()}, arc_episodes=episodes))
    return dict(run=str(run.resolve()), status='completed', official_last_sim_s=manifest.get('last_sim_s'),
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(), agents=agents,
        method=dict(input='Only completed run manifest, own public observations, control-events and recorder counters; no judge/images/hidden states.',
            mode='planner_goal_mode is counted only on new navigation commands; radio-only events can carry cached diagnostics. '
                 'orbit_arc means arc goal was used, not necessarily that the curvature primitive won or the engine flew a circle.',
            point='Own same-event legal radio packet, decoded and mission-matched by the approach analyzer. No cached point substitution. '
                  'Quantized public point may be a local visual fix instead of exact planner target; missing point stays unknown.',
            requested_rate=f'wrap(recovered waypoint bearing - observed own heading) / {command_period} seconds; '
                           'this assumed planner command period is explicit and configurable, not the measured event gap.',
            actual_rate='wrap(next navigation-event own heading - current own heading) / observed elapsed time. '
                        'Compare adjacent navigation events only, gap <= min(1s, 2 * measured median positive interval).',
            duration='known_command_hold_s sums observed intervals to the next navigation command, attributed to their starting mode. '
                     'No duration beyond last command or across gaps. These are command-hold intervals, not proof of continuous visual capture.',
            limits='Event loss counters must be inspected before treating navigation history as complete. '
                   'The underlying autopilot is not identified by a rate ratio. Different public target updates also change radius. '
                   'No control-events file means unknown, never reconstructed completeness from sparse observations.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--command-period', type=float, default=.5)
    parser.add_argument('--include-events', action='store_true')
    args = parser.parse_args()
    result = analyze(args.run, args.command_period, args.include_events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(args.output), agents=[dict(uid=a['uid'], status=a['status'],
        orbit_arc=a['modes'].get('orbit_arc'), episodes=len(a.get('arc_episodes', []))) for a in result['agents']]),
        ensure_ascii=False))


if __name__ == '__main__':
    main()
