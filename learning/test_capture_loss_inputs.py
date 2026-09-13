"""Exact public source contracts, with no Agent or simulator execution."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from analyze_capture_loss_inputs import analyze
from analyze_capture_geometry import SUPPORTED_SOURCES


class CaptureLossInputTests(unittest.TestCase):
    def test_uncompleted_run_is_rejected_before_other_file_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'run.json').write_text('{"status":"running"}', encoding='utf-8')
            original = Path.read_bytes

            def guarded(path):
                self.assertEqual(path, run / 'run.json')
                return original(path)

            with patch.object(Path, 'read_bytes', guarded), self.assertRaisesRegex(ValueError, 'completed'):
                analyze(run)

    def test_completed_exact_sources_missing_images_and_shared_geometry_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'run.json').write_text('{"status":"completed"}', encoding='utf-8')
            (run / 'runner-call.json').write_text(json.dumps(dict(sources=SUPPORTED_SOURCES)), encoding='utf-8')
            folder = run / 'observations' / 'alpha'
            folder.mkdir(parents=True)
            first = hashlib.sha256(b'first source').hexdigest()
            missing = hashlib.sha256(b'unretained exact source').hexdigest()
            (folder / (first + '.image')).write_bytes(b'first source')
            box = dict(x1=500, y1=370, x2=520, y2=390, width=1024, height=768,
                       category='true_vehicle', confidence=.99, class_margin=.98)
            observations, snapshots = [], []
            for i, digest in enumerate((first, missing)):
                source = 1. + i*.5
                diag = dict(receipt_first_seen_sim_s=source, chosen_pixel=box if i == 0 else None,
                    geo_estimate=None, pixel_hits=3 if i == 0 else 0, pixel_identity_hits=3 if i == 0 else 0,
                    motion_hits=2 if i == 0 else 0, pixel_motion_px=4. if i == 0 else None,
                    capture=dict(owner='alpha', partner='bravo', mission=1, phase='APPROACH',
                                 own_visual=i == 0, identity_last_true_s=1.))
                observations.append(dict(score_sim_s=source+.5, photo_sha256=first,
                    boxes_photo_sha256=digest, boxes=[box], diagnostics=diag, commands=[]))
                snapshots.append(dict(recorded_at_s=source+.5, source_receipt_sim_s=source,
                    source_image_sha256=digest, enabled=True, pixel_hits=diag['pixel_hits'],
                    locate_called=i == 0, box=diag['chosen_pixel'], geo_estimate=None,
                    geometry=dict(last_pose=[27., 125., 500., 0., 0., -80., 30.], last_digest=digest,
                        last_time=source, status='PLANE_ESTIMATED', fits=[],
                        homography=[[1, 0, 0], [0, 1, 0], [0, 0, 1]] if i else None,
                        pair_old_digest=first if i else None)))
            for name, records in [('observations.jsonl', observations), ('geometry-inputs.jsonl', snapshots)]:
                (folder / name).write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
            # The dense recorder has receipt time but no image digest; only a
            # unique source at that exact time may resolve a loss event.
            controls = [dict(score_sim_s=r['score_sim_s'], diagnostics=r['diagnostics'],
                commands=[dict(verb='gimbal.set', params=dict(tilt_deg=-70.))]) for r in observations]
            (folder / 'control-events.jsonl').write_text('\n'.join(json.dumps(r) for r in controls), encoding='utf-8')
            recording = dict(key_frames=[dict(source_photo_sha256=first, source_receipt_s=1.,
                receipt_pose_status='exact_receipt_time_and_digest_match',
                source_receipt_pose=dict(uid='alpha', gimbal_pan=12.)),
                # A nearby pose with the correct digest is still not an exact match.
                dict(source_photo_sha256=missing, source_receipt_s=1.5001,
                     receipt_pose_status='exact_receipt_time_and_digest_match',
                     source_receipt_pose=dict(uid='alpha', gimbal_pan=99.))])
            (folder / 'capture-recording.json').write_text(json.dumps(recording), encoding='utf-8')
            result = analyze(run, max_examples=3)
            strong = next(e for e in result['examples'] if e['kind'] == 'strong_true_motion_without_geo')
            self.assertEqual(strong['sources']['current']['geometry']['reason'], 'INSUFFICIENT_RECENT_FITS')
            self.assertTrue(strong['motion_evidence']['valid'])
            self.assertEqual(strong['sources']['current']['receipt_pose']['value']['gimbal_pan'], 12.)
            loss = next(e for e in result['examples'] if e['kind'] == 'owner_visual_lost')
            current = loss['sources']['current']
            self.assertEqual(current['key']['digest'], missing)
            self.assertEqual(current['image']['status'], 'missing')
            self.assertIsNone(current['receipt_pose']['value'])
            self.assertEqual(current['geometry']['reason'], 'NOT_CALLED')
            self.assertEqual(current['geometry']['homography']['old_source_key']['digest'], first)
            self.assertEqual(loss['sources']['previous_recorded_source']['image']['status'], 'hash_verified')
            self.assertEqual(loss['source_key_resolution'], 'unique_geometry_source_at_exact_recorded_receipt')
            self.assertEqual(loss['returned_controls']['status'], 'available')
            self.assertEqual(loss['returned_controls']['total'], 2)
            json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
