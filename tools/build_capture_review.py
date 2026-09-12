"""Review completed capture missions using only hash-matched public RGB photos.

Example: python tools/build_capture_review.py RUN --output artifacts/checks/capture-review
Writes at most two JPEG contact sheets and a JSON selection/provenance manifest.
No official evaluation, judge trace, hidden state, or online Agent is imported.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


ACTIVE = {'OFFER', 'APPROACH', 'TRACK_PAIR', 'RECOVER'}
CARD_W, CARD_H = 840, 484
PAGE_LIMIT, CARDS_PER_PAGE = 2, 12


def capture(row):
    return row.get('diagnostics', {}).get('capture', {})


def load_missions(run_dir):
    # Check this before opening observation logs or any image from the run.
    status = json.loads((run_dir / 'run.json').read_text(encoding='utf-8'))
    if status.get('status') != 'completed':
        raise ValueError('Only a run with run.json status=completed may be reviewed')
    missions = defaultdict(list)
    for log in sorted((run_dir / 'observations').glob('*/observations.jsonl')):
        uid = log.parent.name
        for line in log.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            c = capture(row)
            if (uid not in (c.get('owner'), c.get('partner')) or not c.get('mission')
                    or c.get('phase') not in ACTIVE | {'RELEASE'}):
                continue
            if not math.isfinite(row.get('score_sim_s', math.nan)):
                continue
            missions[(uid, str(c['owner']), c['mission'])].append(row)
    for rows in missions.values():
        rows.sort(key=lambda r: r['score_sim_s'])
    return missions


def valid_photo(row, directory, cache, rejected):
    digest = row.get('boxes_photo_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        return None
    path = directory / (digest + '.image')
    if path not in cache:
        reason = None
        if not path.is_file():
            reason = 'boxes source image was not retained'
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            reason = 'image bytes do not match boxes_photo_sha256'
        else:
            try:
                with Image.open(path) as im:
                    im.verify()
            except (OSError, ValueError):
                reason = 'image could not be decoded'
        cache[path] = reason is None
        if reason:
            rejected.append(dict(path=str(path), reason=reason))
    return path if cache[path] else None


def evenly_spaced(items, limit):
    if len(items) <= limit:
        return items
    if limit == 1:
        return items[:1]
    return [items[round(i * (len(items) - 1) / (limit - 1))] for i in range(limit)]


def select_cards(run_dir, missions_per_uav, max_offset_s):
    missions = load_missions(run_dir)
    by_uid = defaultdict(list)
    for key, rows in missions.items():
        by_uid[key[0]].append((key, rows))
    selected, omitted, rejected, cache = [], [], [], {}
    for uid, groups in sorted(by_uid.items()):
        groups.sort(key=lambda item: item[1][0]['score_sim_s'])
        retained = evenly_spaced(groups, missions_per_uav)
        retained_keys = {key for key, _ in retained}
        for key, _ in groups:
            if key not in retained_keys:
                omitted.append(dict(uid=uid, mission=f'{key[1]}:{key[2]}',
                                    reason='per-UAV mission limit; first/last are preferred'))
        for key, rows in retained:
            label = f'{key[1]}:{key[2]}'
            active = [r for r in rows if capture(r)['phase'] in ACTIVE]
            visual = [r for r in active if capture(r).get('own_visual')]
            released = [r for r in rows if capture(r)['phase'] == 'RELEASE']
            events = []
            if active:
                first = active[0]
                # Preserve the actual first state; do not silently replace a
                # discovery with a later approach or a lost-visual frame.
                first_phase = capture(first)['phase']
                events.append(('DISCOVERY' if uid == key[1] else 'ASSIGNMENT', first,
                               [r for r in active if capture(r)['phase'] == first_phase]))
            if visual:
                events.extend((('FIRST_VISUAL', visual[0], visual),
                               ('LAST_VISUAL', visual[-1], visual)))
            else:
                omitted.append(dict(uid=uid, mission=label, reason='no own_visual samples'))
            if released:
                events.append(('RELEASE', released[0], released))
            else:
                omitted.append(dict(uid=uid, mission=label, reason='no RELEASE sample before run end'))
            used = {}
            for event, anchor, candidates in events:
                candidates = sorted((r for r in candidates
                    if abs(r['score_sim_s'] - anchor['score_sim_s']) <= max_offset_s),
                    key=lambda r: (abs(r['score_sim_s'] - anchor['score_sim_s']), r['score_sim_s']))
                choice = None
                for row in candidates:
                    path = valid_photo(row, run_dir / 'observations' / uid, cache, rejected)
                    if path:
                        choice = row, path
                        break
                if choice is None:
                    omitted.append(dict(uid=uid, mission=label, event=event,
                        event_sim_s=anchor['score_sim_s'],
                        reason=f'no hash-matched source photo in same event state within {max_offset_s:g}s'))
                    continue
                row, path = choice
                c = capture(row)
                # The same image can occur in different control phases. Keep
                # those separate, while merging first/last labels on one state.
                dedup = (row['boxes_photo_sha256'], c['phase'], bool(c.get('own_visual')))
                event_info = dict(event=event, event_sim_s=anchor['score_sim_s'],
                                  selected_sim_s=row['score_sim_s'])
                if dedup in used:
                    used[dedup]['events'].append(event_info)
                else:
                    card = dict(uid=uid, mission=label, row=row, path=path, events=[event_info])
                    used[dedup] = card
                    selected.append(card)
    # Interleave UAVs if the global two-page bound is reached.
    by_uid = defaultdict(list)
    for card in selected:
        by_uid[card['uid']].append(card)
    fair = []
    while any(by_uid.values()):
        for cards in by_uid.values():
            if cards:
                fair.append(cards.pop(0))
    limit = PAGE_LIMIT * CARDS_PER_PAGE
    for card in fair[limit:]:
        omitted.append(dict(uid=card['uid'], mission=card['mission'],
                            reason='global two-page panel limit', events=card['events']))
    return fair[:limit], omitted, rejected, len(missions)


def font(size):
    for name in ('C:/Windows/Fonts/segoeui.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def bounded_box(box, size):
    if not box or (box.get('width'), box.get('height')) != size:
        return None
    try:
        values = tuple(float(box[k]) for k in ('x1', 'y1', 'x2', 'y2'))
    except (KeyError, TypeError, ValueError):
        return None
    if (not all(math.isfinite(v) for v in values) or
            not 0 <= values[0] < values[2] <= size[0] or
            not 0 <= values[1] < values[3] <= size[1]):
        return None
    return values


def render_card(card):
    row = card['row']; d = row['diagnostics']; c = capture(row)
    with Image.open(card['path']) as source:
        photo = source.convert('RGB')
    box = d.get('chosen_pixel')
    coordinates = bounded_box(box, photo.size)
    panel = Image.new('RGB', (CARD_W, CARD_H), '#ffffff')
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, CARD_W - 1, 83), fill='#edf2f6')
    events = ' + '.join(e['event'] for e in card['events'])
    draw.text((10, 6), f"UAV {card['uid']} | local mission {card['mission']} | {events}",
              font=font(18), fill='#142b40')
    receipt = d.get('receipt_first_seen_sim_s')
    source_time = f'{receipt:.2f}s' if isinstance(receipt, (float, int)) else 'unknown'
    draw.text((10, 32), f"log {row['score_sim_s']:.2f}s | source receipt {source_time} | {c['phase']}"
              f" | own_visual={int(bool(c.get('own_visual')))}", font=font(17), fill='#142b40')
    confidence = f"{box.get('confidence', 0.):.3f}" if coordinates else 'none'
    category = str(box.get('category', 'unknown')) if coordinates else 'no chosen candidate'
    draw.text((10, 57), f"model: {category} | confidence={confidence} | pixel hits={d.get('pixel_hits', 0)}",
              font=font(17), fill='#142b40')
    full = photo.copy()
    if coordinates:
        ImageDraw.Draw(full).rectangle(coordinates, outline='#ff3030', width=3)
        x1, y1, x2, y2 = coordinates
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        radius = max(64, math.ceil(max(x2 - x1, y2 - y1)))
    else:
        center = (photo.width / 2, photo.height / 2)
        radius = 64
    left = min(max(0, round(center[0] - radius)), max(0, photo.width - radius * 2))
    top = min(max(0, round(center[1] - radius)), max(0, photo.height - radius * 2))
    crop_bounds = (left, top, min(photo.width, left + radius * 2), min(photo.height, top + radius * 2))
    crop = photo.crop(crop_bounds)
    if coordinates:
        ImageDraw.Draw(crop).rectangle((x1-left, y1-top, x2-left, y2-top), outline='#ff3030', width=1)
    full.thumbnail((512, 384), Image.Resampling.LANCZOS)
    panel.paste(full, (8 + (512-full.width)//2, 92))
    crop.thumbnail((280, 280), Image.Resampling.LANCZOS)
    # Enlarge the diagnostic crop, but never infer missing image details.
    factor = min(280/crop.width, 280/crop.height)
    crop = crop.resize((round(crop.width*factor), round(crop.height*factor)), Image.Resampling.LANCZOS)
    panel.paste(crop, (548, 92))
    draw.text((548, 382), 'Chosen candidate crop' if coordinates else 'Center crop; no candidate',
              font=font(17), fill='#142b40')
    anchors = ', '.join(dict.fromkeys(f"{e['event_sim_s']:.2f}s" for e in card['events']))
    draw.text((548, 408), f'Event time: {anchors}', font=font(14), fill='#42576b')
    draw.text((548, 434), 'Red box = model selection', font=font(16), fill='#42576b')
    draw.text((548, 456), 'Source hash verified', font=font(16), fill='#42576b')
    return panel, dict(uid=card['uid'], mission=card['mission'], events=card['events'],
        selected_sim_s=row['score_sim_s'], source_receipt_sim_s=receipt, phase=c['phase'],
        own_visual=bool(c.get('own_visual')), image=str(card['path'].resolve()),
        boxes_photo_sha256=row['boxes_photo_sha256'], chosen_pixel=box,
        box_dimensions_valid=coordinates is not None, crop_bounds=crop_bounds)


def build(run_dir, output, missions_per_uav=2, max_offset_s=1.2):
    cards, omitted, rejected, mission_count = select_cards(run_dir, missions_per_uav, max_offset_s)
    prefix = output.with_suffix('') if output.suffix.lower() in ('.jpg', '.jpeg', '.json') else output
    prefix.parent.mkdir(parents=True, exist_ok=True)
    pages, provenance = [], []
    for start in range(0, max(1, len(cards)), CARDS_PER_PAGE):
        batch = cards[start:start+CARDS_PER_PAGE]
        rows = max(1, math.ceil(len(batch)/2))
        canvas = Image.new('RGB', (2*CARD_W+24, rows*CARD_H+112), '#d4dde5')
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 9), f'{run_dir.name} | completed public-photo review | page {len(pages)+1}',
                  font=font(24), fill='#142b40')
        draw.text((12, 43), 'Image/model evidence only; local mission IDs and own_visual do not prove official capture.',
                  font=font(19), fill='#142b40')
        if not batch:
            draw.text((20, 130), 'No retained hash-matched images at the requested mission stages.',
                      font=font(22), fill='#142b40')
        for i, card in enumerate(batch):
            panel, info = render_card(card)
            canvas.paste(panel, (8+(i%2)*(CARD_W+8), 78+(i//2)*CARD_H))
            info.update(page=len(pages)+1, panel=i+1)
            provenance.append(info)
        draw.text((12, canvas.height-27), f'{len(cards)} panels selected; {len(omitted)} omitted events/missions. '
                  'Exact event and chosen sample times are recorded in the adjacent JSON.', font=font(16), fill='#142b40')
        destination = prefix.parent / f'{prefix.name}-{len(pages)+1:02d}.jpg'
        canvas.save(destination, quality=92, subsampling=0)
        pages.append(str(destination.resolve()))
    manifest = dict(run=str(run_dir.resolve()), input_status='completed', source='own public observations only',
        limits=dict(max_pages=PAGE_LIMIT, max_panels_per_mission=4,
                    missions_per_uav=missions_per_uav, nearest_same_event_offset_s=max_offset_s),
        mission_uav_pairs_found=mission_count, pages=pages, panels=provenance,
        omitted=omitted, rejected_images=rejected,
        notes=['Only boxes_photo_sha256 images with matching file content are displayed.',
               'No current photo is substituted for a missing detector source photo.',
               'Events may share one photo; displayed phase belongs to the selected log sample.',
               'Receipt times are not verified capture timestamps; model labels are not ground truth.'])
    destination = prefix.parent / f'{prefix.name}.json'
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(pages=pages, manifest=str(destination.resolve()), panels=len(provenance), omitted=len(omitted))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='Output prefix, optionally ending in .jpg')
    parser.add_argument('--missions-per-uav', type=int, choices=range(1, 5), default=2)
    parser.add_argument('--max-event-offset', type=float, default=1.2,
                        help='Maximum distance in seconds to a saved image in the same event state')
    args = parser.parse_args()
    if not math.isfinite(args.max_event_offset) or not 0 <= args.max_event_offset <= 3.:
        parser.error('--max-event-offset must be between 0 and 3 seconds')
    try:
        result = build(args.run, args.output, args.missions_per_uav, args.max_event_offset)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Capture review failed: {exc}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
