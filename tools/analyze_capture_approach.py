"""Public-only approach diagnostics; requires a completed run before opening observations."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import sys

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
from zqhj_comm import decode
from zqhj_state import LocalFrame, valid_geo

THRESHOLDS = (410, 650, 700)
NAV_VERBS = {'set_destination', 'set_heading', 'set_speed'}


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def stats(values):
    good = [v for v in values if finite(v)]
    return dict(known=len(good), unknown=len(values)-len(good),
                min=min(good) if good else None, max=max(good) if good else None,
                median=median(good) if good else None)


def frame_from_rows(rows):
    # Same public frame origin rule as EntryAgent; no target or judge data.
    for row in rows:
        own = row.get('own') or {}
        if not valid_geo(own.get('lat'), own.get('lon')):
            continue
        area = (row.get('public_briefing') or {}).get('mission_area') or {}
        if (valid_geo(area.get('lat_min'), area.get('lon_min')) and
                valid_geo(area.get('lat_max'), area.get('lon_max'))):
            return LocalFrame((area['lat_min']+area['lat_max'])/2,
                              (area['lon_min']+area['lon_max'])/2)
        return LocalFrame(own['lat'], own['lon'])
    return None


def sample(row, uid, roster, frame):
    t = row['score_sim_s']
    d = row.get('diagnostics') or {}
    c = d.get('capture') or {}
    own = row.get('own') or {}
    commands = row.get('commands') or []
    owner, number, partner = c.get('owner'), c.get('mission'), c.get('partner')
    key = (str(owner), number) if owner is not None and number is not None else None
    role = ('owner' if uid == owner else 'partner' if uid == partner else 'third') if key else 'unassigned'
    s = dict(t=t, key=key, role=role, partner=partner, phase=c.get('phase', 'unknown'),
             reason=c.get('reason', 'unknown'), own_visual=c.get('own_visual'),
             actual_speed_mps=own.get('speed') if finite(own.get('speed')) else None,
             range_m=None, point=None, position=None, radial_own_velocity_mps=None,
             source='no_same_sample_broadcast', packet_source_age_s=None,
             broadcast_visible=None, source_packet_time_s=None)
    nav = [cmd for cmd in commands if cmd.get('verb') in NAV_VERBS]
    s['new_navigation_command'] = bool(nav)
    s['plan_feasible'] = d.get('plan_feasible') if nav and isinstance(d.get('plan_feasible'), bool) else None
    s['clearance_m'] = d.get('clearance_m') if nav and finite(d.get('clearance_m')) else None
    s['planner_reason'] = d.get('planner_reason', 'unknown') if nav else 'not_new_navigation_sample'
    s['requested_cruise_mps'] = d.get('cruise_speed') if nav else None
    if frame and valid_geo(own.get('lat'), own.get('lon')):
        s['position'] = frame.xy(own['lat'], own['lon'])
    broadcasts = [cmd for cmd in commands if cmd.get('verb') == 'comm.broadcast']
    if not key:
        return s
    slot_uid = lambda slot: roster[slot-1] if 1 <= slot <= len(roster) else None
    def matches(p):
        return (p is not None and len(roster) == 3 and p.capture and p.track_id == number and
                slot_uid(p.owner_slot) == owner and slot_uid(p.partner_slot) == partner)
    if broadcasts:
        packets = [decode((cmd.get('params') or {}).get('payload')) for cmd in broadcasts]
        if len(packets) != 1 or packets[0] is None:
            s['source'] = 'invalid_or_ambiguous_broadcast'
            return s
        p = packets[0]
        if not matches(p):
            s['source'] = 'broadcast_mission_or_roster_mismatch'
            return s
        # Encoder truncates packet time to deciseconds.
        if not -1e-6 <= t-p.time_s <= .100001:
            s['source'] = 'broadcast_time_not_current_sample'
            return s
        source = 'same_sample_own_public_broadcast'
    else:
        received = []
        for message in row.get('inbox') or []:
            if (message.get('sender_uid') != owner or not finite(message.get('recv_time'))
                    or message['recv_time'] > t+1e-6):
                continue
            packet = decode(message.get('payload'))
            if matches(packet) and 0 <= t-packet.time_s <= 1.5:
                received.append((packet, message['recv_time']))
        if not received:
            s['source'] = 'no_same_sample_broadcast_or_fresh_received_owner_point'
            return s
        p, received_at = max(received, key=lambda item: (item[0].time_s, item[1]))
        s['owner_packet_received_s'] = received_at
        source = 'fresh_owner_broadcast_received_by_this_agent_proxy'
    if frame is None or s['position'] is None:
        s['source'] = 'own_position_or_public_frame_missing'
        return s
    source_age = t-p.time_s+p.age_s
    dt = max(0., min(3., source_age))
    origin = frame.xy(p.target_lat, p.target_lon)
    point = (origin[0]+p.target_vx*dt, origin[1]+p.target_vy*dt)
    s.update(source=source, point=point,
             range_m=math.dist(s['position'], point), packet_source_age_s=source_age,
             broadcast_visible=p.visible, source_packet_time_s=p.time_s)
    if s['range_m'] > 0 and finite(own.get('heading_deg')) and finite(s['actual_speed_mps']):
        h = math.radians(own['heading_deg'])
        v = (s['actual_speed_mps']*math.sin(h), s['actual_speed_mps']*math.cos(h))
        s['radial_own_velocity_mps'] = sum(v[i]*(point[i]-s['position'][i]) for i in (0, 1))/s['range_m']
    return s


def summarize(samples, max_gap):
    distances = [s['range_m'] for s in samples]
    known = [s for s in samples if finite(s['range_m'])]
    consecutive = []
    excluded = Counter()
    for a, b in zip(samples, samples[1:]):
        dt = b['t']-a['t']
        if b['index'] != a['index']+1:
            excluded['nonadjacent_public_samples'] += 1
        elif dt <= 0 or dt > max_gap:
            excluded['duplicate_time_or_sampling_gap'] += 1
        elif a['range_m'] is None or b['range_m'] is None:
            excluded['missing_broadcast_distance'] += 1
        else:
            frozen = math.dist(b['position'], a['point'])
            consecutive.append((a, b, dt, a['range_m']-frozen, frozen-b['range_m']))
    thresholds = {}
    for threshold in THRESHOLDS:
        below = [s for s in known if s['range_m'] <= threshold]
        crossings = []
        for a, b, _, _, _ in consecutive:
            if (a['range_m'] <= threshold) != (b['range_m'] <= threshold):
                crossings.append(dict(direction='inward' if b['range_m'] <= threshold else 'outward',
                    bracket_s=[a['t'], b['t']], ranges_m=[a['range_m'], b['range_m']]))
        thresholds[str(threshold)] = dict(samples_at_or_below=len(below),
            first_sample_at_or_below_s=below[0]['t'] if below else None,
            inward_crossings=sum(e['direction'] == 'inward' for e in crossings),
            outward_crossings=sum(e['direction'] == 'outward' for e in crossings), crossings=crossings)
    plan = [s for s in samples if s['new_navigation_command']]
    range_summary = stats(distances)
    range_summary.update(first_sample_m=distances[0] if distances else None,
        last_sample_m=distances[-1] if distances else None,
        first_known=dict(t=known[0]['t'], value=known[0]['range_m']) if known else None,
        last_known=dict(t=known[-1]['t'], value=known[-1]['range_m']) if known else None,
        net_first_to_last_known_reduction_m=known[0]['range_m']-known[-1]['range_m'] if known else None)
    return dict(samples=len(samples), first_s=samples[0]['t'] if samples else None,
        last_s=samples[-1]['t'] if samples else None,
        phases=Counter(s['phase'] for s in samples), range_to_broadcast_point_m=range_summary,
        actual_speed_mps=stats([s['actual_speed_mps'] for s in samples]),
        requested_cruise_mps=stats([s['requested_cruise_mps'] for s in plan]),
        own_velocity_toward_broadcast_point_mps=stats([s['radial_own_velocity_mps'] for s in samples]),
        radial_progress=dict(adjacent_pairs=len(consecutive), excluded_pairs=excluded,
            covered_interval_s=sum(p[2] for p in consecutive),
            net_range_reduction_m=sum(p[3]+p[4] for p in consecutive) if consecutive else None,
            own_displacement_toward_previous_point_m=sum(p[3] for p in consecutive) if consecutive else None,
            moving_or_updated_point_contribution_m=sum(p[4] for p in consecutive) if consecutive else None,
            point_source_changes=sum(a['source'] != b['source'] for a, b, _, _, _ in consecutive),
            net_closing_speed_mps=stats([(p[3]+p[4])/p[2] for p in consecutive])),
        thresholds_m=thresholds, new_navigation_samples=len(plan),
        planning=Counter('feasible' if s['plan_feasible'] is True else
                         'infeasible' if s['plan_feasible'] is False else 'unknown' for s in plan),
        planner_reasons=Counter(s['planner_reason'] for s in plan),
        clearance_m=stats([s['clearance_m'] for s in plan]),
        source_counts=Counter(s['source'] for s in samples),
        broadcast_source_age_s=stats([s['packet_source_age_s'] for s in samples]),
        own_visual_samples=sum(s['own_visual'] is True for s in samples))


def approach_segments(samples, max_gap):
    segments, current = [], []
    for s in samples:
        same = (current and s['key'] == current[-1]['key'] and s['role'] == current[-1]['role']
                and s['partner'] == current[-1]['partner'] and 0 < s['t']-current[-1]['t'] <= max_gap)
        if current and (s['phase'] != 'APPROACH' or not same):
            segments.append(current)
            current = []
        if s['phase'] == 'APPROACH' and s['key'] is not None:
            current.append(s)
    if current:
        segments.append(current)
    return segments


def analyze(run):
    run = Path(run)
    manifest_path = run/'run.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('status') != 'completed':
        raise ValueError('run must be completed before reading public observations')
    paths = sorted((run/'observations').glob('*/observations.jsonl'))
    roster = [p.parent.name for p in paths]
    agents = []
    for path in paths:
        raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
        times = [r.get('score_sim_s') for r in rows]
        if any(not finite(t) or t < 0 for t in times) or any(b < a for a, b in zip(times, times[1:])):
            raise ValueError('public times must be finite, nonnegative and monotonic')
        end = manifest.get('last_sim_s')
        if finite(end) and any(t > end+1e-6 for t in times):
            raise ValueError('public sample exceeds completed official ending')
        intervals = [b-a for a, b in zip(times, times[1:]) if b > a]
        cadence = median(intervals) if intervals else None
        max_gap = max(1., 2*cadence) if cadence else 1.
        frame = frame_from_rows(rows)
        samples = [sample(row, path.parent.name, roster, frame) for row in rows]
        for i, s in enumerate(samples):
            s['index'] = i
        missions = {}
        for s in samples:
            if s['key'] is None:
                continue
            key = json.dumps(s['key'], separators=(',', ':'))
            missions.setdefault(key, dict(owner=s['key'][0], mission=s['key'][1], roles={}))
            group = missions[key]['roles'].setdefault(s['role'], [])
            group.append(s)
        for m in missions.values():
            for role, group in m['roles'].items():
                # Roles remain distinct if a partner is reassigned in one mission.
                summary = summarize(group, max_gap)
                summary['partners_seen'] = sorted({s['partner'] for s in group if s['partner'] is not None})
                summary['approach'] = summarize([s for s in group if s['phase'] == 'APPROACH'], max_gap)
                m['roles'][role] = summary
        segments = []
        for group in approach_segments(samples, max_gap):
            first, last = group[0], group[-1]
            previous = samples[first['index']-1] if first['index'] > 0 else None
            following = samples[last['index']+1] if last['index']+1 < len(samples) else None
            entry = [previous['t'], first['t']] if previous and first['t']-previous['t'] <= max_gap else None
            exit_window = [last['t'], following['t']] if following and following['t']-last['t'] <= max_gap else None
            segments.append(dict(owner=first['key'][0], mission=first['key'][1], role=first['role'],
                partner=first['partner'], sample_span_s=last['t']-first['t'],
                entry_bracket_s=entry, exit_bracket_s=exit_window,
                duration_upper_bound_s=exit_window[1]-entry[0] if entry and exit_window else None,
                next_phase=following['phase'] if following else None,
                next_reason=following['reason'] if following else None, **summarize(group, max_gap)))
        agents.append(dict(uid=path.parent.name, observations_sha256=hashlib.sha256(raw).hexdigest(),
            public_samples=len(rows), median_interval_s=cadence, max_adjacent_gap_s=max_gap,
            missions=list(missions.values()), approach_segments=segments,
            partner_approach_sample_span_s=sum(s['sample_span_s'] for s in segments if s['role'] == 'partner')))
    return dict(run=str(run.resolve()), run_status=manifest['status'], official_last_sim_s=manifest.get('last_sim_s'),
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        decoder_sha256=hashlib.sha256((SRC/'zqhj_comm.py').read_bytes()).hexdigest(), agents=agents,
        method=dict(inputs='Only completed run.json and public observations.jsonl. No judge, images, engine or hidden positions.',
            point='Prefer same-row own comm.broadcast, verified mission/owner/partner against sorted three-agent public roster. '
                  'If absent, use only this agent inbox latest matching owner packet already received, with packet age <=1.5s; '
                  'label explicitly as received-owner-point proxy. Never read another agent position for this calculation. '
                  'Decode target geo and velocity; predict with clamp(now - packet_time + age, 0, 3) seconds. '
                  'No usable matching source means unknown. Do not replay hidden local mission acceptance/state.',
            limits='Broadcasts are quantized (geo 1e-6 deg, time/age 0.1s, velocity 0.5m/s). '
                   'Visible broadcasts may carry local visual fixes instead of the precise planner mission point. '
                   'Received owner points may not have been accepted by the local mission gate. '
                   'Distances are to that public nominated point, not verified target range or hidden planner state.',
            planning='Feasibility, clearance and requested cruise counted only when this sample emits a navigation command; '
                     'otherwise diagnostics can be cached. Missing/nonfinite clearance is unknown, not infinity or zero.',
            radial='Positive means closing. Own velocity projection and displacement toward the previous public point '
                   'separate flight progress from motion/updates of the nominated point. Net range change includes both.',
            timing='APPROACH sample spans are observed lower bounds, not exact continuous durations. Entry/exit brackets '
                   'and upper bounds require adjacent public samples. Split phase/role/partner/mission changes and gaps '
                   '> max(1s, 2 * measured median interval). No interpolation through missing distances.',
            thresholds='410/650/700m crossings are brackets between adjacent known public distances, not exact crossing times. '
                       'First known point may already be inside; unknown intervals cannot establish a crossing.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    compact = []
    for agent in result['agents']:
        for s in agent['approach_segments']:
            if s['role'] == 'partner':
                r = s['range_to_broadcast_point_m']
                compact.append(dict(uid=agent['uid'], owner=s['owner'], mission=s['mission'],
                    start_s=s['first_s'], span_s=s['sample_span_s'], distance_start_m=r['first_sample_m'],
                    distance_min_m=r['min'], distance_end_m=r['last_sample_m'],
                    speed_mps=s['actual_speed_mps'], planning=s['planning']))
    print(json.dumps(dict(output=str(args.output), partner_approach_segments=compact), ensure_ascii=False))


if __name__ == '__main__':
    main()
