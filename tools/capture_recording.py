"""Bounded per-agent public recording, with no I/O and no Agent/SDK imports.

Runner integration (after every decide, without the observations.jsonl 0.5s gate)::

    recorder.record(now, obs.self, self.diagnostics, commands,
                    source_digest=self.photo_digest)

Create one recorder per agent. Call export() only after the run; the runner owns
serialization. Receipt poses are observations at that exact receipt timestamp,
never claimed to be calibrated camera exposure poses. Image bytes are shared by
reference, including between the recent ring and retained key frames.
"""
from collections import Counter, OrderedDict, deque
import hashlib
import json
import math


KEY_PHASES = {'VERIFY', 'OFFER', 'APPROACH', 'TRACK_PAIR', 'RECOVER'}
POSE_FIELDS = ('uid', 'lat', 'lon', 'alt', 'heading_deg', 'speed', 'gimbal_pan',
               'gimbal_tilt', 'gimbal_fov_deg', 'status')
DIAG_FIELDS = ('visual_tracker', 'state', 'geometry_state', 'vision_state', 'identity', 'pixel_hits',
               'pixel_identity_hits', 'motion_hits', 'fast_geo_hits', 'receipt_first_seen_sim_s',
               'plan_feasible', 'planner_reason', 'clearance_m', 'cruise_speed', 'capture', 'chosen_pixel',
               'pixel_motion_px', 'pixel_ground_speed_mps', 'motion_verified_until', 'capture_identity_memory')


def get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def snapshot(value):
    # Copy small metadata, not image bytes; do not retain mutable SDK dictionaries.
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return json.loads(encoded), len(encoded.encode('utf-8'))


class CaptureRecorder:
    def __init__(self, uid, *, recent_receipts=64, recent_processed=8,
                 max_images=500, max_image_bytes=96*1024*1024, max_saved_frames=400,
                 max_events=6000, max_event_bytes=16*1024*1024, max_event_size=65536):
        limits = dict(recent_receipts=recent_receipts, recent_processed=recent_processed,
            max_images=max_images, max_image_bytes=max_image_bytes, max_saved_frames=max_saved_frames,
            max_events=max_events, max_event_bytes=max_event_bytes, max_event_size=max_event_size)
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in limits.values()):
            raise ValueError('all recording limits must be positive integers')
        self.uid = str(uid)
        if len(self.uid) > 128:
            raise ValueError('uid exceeds recording metadata bound')
        self.limits = limits
        self.receipts = deque(maxlen=recent_receipts)
        self.processed = deque(maxlen=recent_processed)
        self.images = OrderedDict()
        self.saved_frames = OrderedDict()
        self.events = []
        self.image_bytes = self.event_bytes = 0
        self.dropped = Counter()
        self.last_time = None
        self.last_processed_key = None

    def _remove_image(self, digest):
        self.image_bytes -= len(self.images.pop(digest))

    def _forget_saved_image(self, digest):
        for key in list(self.saved_frames):
            if key[0] == digest:
                del self.saved_frames[key]
                self.dropped['saved_frame_evicted_for_image_capacity'] += 1

    @staticmethod
    def _retention_priority(frame):
        # Late capture failures must not be crowded out by early VERIFY frames.
        return (int(frame.get('retention_phase',frame['trigger_phase']) != 'VERIFY'), frame['source_receipt_s'])

    def _cache_image(self, digest, photo):
        if digest in self.images:
            return
        if len(photo) > self.limits['max_image_bytes']:
            self.dropped['image_too_large'] += 1
            return
        while (len(self.images) >= self.limits['max_images'] or
               self.image_bytes+len(photo) > self.limits['max_image_bytes']):
            protected = {r['source_photo_sha256'] for r in self.saved_frames.values()}
            recent = {r['photo_sha256'] for r in self.receipts}
            recent.update(r['source_photo_sha256'] for r in self.processed)
            victim = next((key for key in self.images if key not in protected and key not in recent), None)
            if victim is None:
                saved = [f for f in self.saved_frames.values() if f['source_photo_sha256'] not in recent]
                if saved:
                    victim = min(saved,key=self._retention_priority)['source_photo_sha256']
                else:
                    # Extremely small configured budgets may not fit the whole
                    # working ring. Keep accepting new bytes instead of pinning
                    # an early prefix for the remainder of the game.
                    victim = next(iter(self.images),None)
            if victim is None:
                self.dropped['image_capacity'] += 1;return
            self._forget_saved_image(victim)
            self._remove_image(victim)
            self.dropped['recent_image_evicted_for_capacity'] += 1
        self.images[digest] = photo
        self.image_bytes += len(photo)

    def _prune_images(self):
        wanted = {r['photo_sha256'] for r in self.receipts}
        wanted.update(r['source_photo_sha256'] for r in self.processed)
        wanted.update(r['source_photo_sha256'] for r in self.saved_frames.values())
        for digest in list(self.images):
            if digest not in wanted:
                self._remove_image(digest)

    def _save_frame(self, frame, now, phase):
        key = (frame['source_photo_sha256'], frame['source_receipt_s'])
        if key in self.saved_frames:
            if phase != 'VERIFY':self.saved_frames[key]['retention_phase'] = phase
            return
        if frame['source_photo_sha256'] not in self.images:
            self.dropped['key_frame_image_unavailable'] += 1
            return
        if len(self.saved_frames) >= self.limits['max_saved_frames']:
            victim = min(self.saved_frames,key=lambda item:self._retention_priority(self.saved_frames[item]))
            incoming = dict(frame,trigger_phase=phase)
            if self._retention_priority(incoming) <= self._retention_priority(self.saved_frames[victim]):
                self.dropped['saved_frame_capacity'] += 1;return
            del self.saved_frames[victim]
            self.dropped['saved_frame_evicted_for_frame_capacity'] += 1
        # Reuse the immutable metadata snapshot held by the processed ring.
        self.saved_frames[key] = dict(frame, retained_at_s=now, trigger_phase=phase, retention_phase=phase)

    def record(self, now, own, diagnostics, commands, *, source_digest=None):
        """Call every decide, even when commands=[]; never samples controls by time.

        source_digest is this agent's processed-photo digest, not current-own-photo
        digest. Missing exact receipt matches stay unknown. Returns False for an
        invalid time/UID; normal capacity loss only increments dropped counters.
        """
        if str(get(own, 'uid')) != self.uid:
            self.dropped['wrong_agent'] += 1
            return False
        if not finite(now) or now < 0 or (self.last_time is not None and now < self.last_time):
            self.dropped['invalid_or_rewound_time'] += 1
            return False
        self.last_time = now
        try:
            pose, pose_size = snapshot({key: get(own, key) for key in POSE_FIELDS})
            diag, diag_size = snapshot({key: diagnostics.get(key) for key in DIAG_FIELDS if key in diagnostics})
        except (TypeError, ValueError, OverflowError):
            self.dropped['invalid_metadata'] += 1
            return False
        if pose_size > self.limits['max_event_size']:
            self.dropped['pose_too_large'] += 1
            return False
        if diag_size > self.limits['max_event_size']:
            self.dropped['diagnostics_too_large'] += 1
            diag = {}
        photo = get(own, 'photo')
        current_digest = None
        if isinstance(photo, bytes) and photo:
            current_digest = hashlib.sha256(photo).hexdigest()
            self._cache_image(current_digest, photo)
        elif photo is not None and not isinstance(photo, bytes):
            self.dropped['unsupported_image_type'] += 1
        if len(self.receipts) == self.receipts.maxlen:
            self.dropped['recent_receipt_expired'] += 1
        self.receipts.append(dict(time_s=now, photo_sha256=current_digest, own=pose))

        # Every nonempty returned command batch gets its own event, including
        # radio-only batches. No 0.5s recorder condition can hide a control call.
        if commands:
            if len(self.events) >= self.limits['max_events']:
                self.dropped['event_count_capacity'] += 1
            else:
                try:
                    event, size = snapshot(dict(score_sim_s=now, own=pose, diagnostics=diag,
                        commands=[dict(verb=get(c, 'verb'), params=get(c, 'params', {})) for c in commands]))
                    if size > self.limits['max_event_size']:
                        self.dropped['event_too_large'] += 1
                    elif self.event_bytes+size > self.limits['max_event_bytes']:
                        self.dropped['event_byte_capacity'] += 1
                    else:
                        self.events.append(event)
                        self.event_bytes += size
                except (TypeError, ValueError, OverflowError):
                    self.dropped['invalid_command_metadata'] += 1

        receipt = diag.get('receipt_first_seen_sim_s')
        valid_digest = (isinstance(source_digest, str) and len(source_digest) == 64
                        and all(c in '0123456789abcdef' for c in source_digest))
        if valid_digest and finite(receipt) and receipt <= now+1e-6:
            key = source_digest, receipt
            if key != self.last_processed_key:
                exact = [r for r in self.receipts if abs(r['time_s']-receipt) <= 1e-6
                         and r['photo_sha256'] == source_digest]
                status = 'exact_receipt_time_and_digest_match' if len(exact) == 1 else 'unknown_no_unique_exact_receipt'
                frame = dict(source_photo_sha256=source_digest, source_receipt_s=receipt,
                    processed_observed_at_s=now, receipt_pose_status=status,
                    source_receipt_pose=exact[0]['own'] if len(exact) == 1 else None,
                    capture_pose_calibrated=False, diagnostics=diag)
                if len(self.processed) == self.processed.maxlen:
                    self.dropped['recent_processed_expired'] += 1
                self.processed.append(frame)
                self.last_processed_key = key
        elif source_digest is not None:
            self.dropped['processed_source_time_unknown_or_future'] += 1
        phase = (diag.get('capture') or {}).get('phase')
        if phase in KEY_PHASES or diag.get('state') == 'VERIFY':
            for frame in self.processed:
                self._save_frame(frame, now, phase or 'VERIFY')
        self._prune_images()
        return True

    def export(self):
        """Return bounded in-memory views for the runner to serialize after run.

        Do not mutate returned views or continue recording while exporting.
        photo_bytes values are the original bytes objects, with no duplicate copy.
        """
        saved_digests = {r['source_photo_sha256'] for r in self.saved_frames.values()}
        return dict(uid=self.uid, limits=dict(self.limits), dropped=dict(self.dropped),
            retention='bounded replacement: working receipt/source ring, capture phases before VERIFY, newer before older',
            payload_budget=dict(unique_image_bytes=self.limits['max_image_bytes'],
                serialized_event_bytes=self.limits['max_event_bytes'],
                metadata_note='Each receipt pose and diagnostic snapshot is <= max_event_size UTF-8 JSON bytes. '
                              'At most recent_receipts poses, recent_processed source records and max_saved_frames retained '
                              'source records; each source record references at most one pose and one diagnostic snapshot. '
                              'Image bytes are never duplicated. Counts bound additional Python object overhead.'),
            retained=dict(image_count=len(self.images), image_bytes=self.image_bytes,
                saved_frames=len(self.saved_frames), recent_receipts=len(self.receipts),
                recent_processed=len(self.processed), events=len(self.events), event_json_bytes=self.event_bytes),
            control_events=self.events, key_frames=list(self.saved_frames.values()),
            photo_bytes={key: value for key, value in self.images.items() if key in saved_digests},
            semantics='Own public receipt observations and returned commands only; not confirmed engine execution. '
                      'Receipt pose is not exposure calibration. Limits count unique image bytes and serialized event bytes; '
                      'Python object overhead is additional but bounded by frame/event/receipt counts and metadata size.')
