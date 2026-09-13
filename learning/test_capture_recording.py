"""No simulator: public recorder isolation, exact source association and hard caps."""
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from capture_recording import CaptureRecorder


def digest(photo):
    return hashlib.sha256(photo).hexdigest()


def own(photo, uid='a', pan=0.):
    return dict(uid=uid, photo=photo, lat=27., lon=125., alt=500., heading_deg=90.,
                speed=32., gimbal_pan=pan, gimbal_tilt=-45., gimbal_fov_deg=30., status='active')


def diag(t, phase='SEARCH'):
    return dict(receipt_first_seen_sim_s=t, capture=dict(phase=phase, owner='a', partner='b', mission=1),
                plan_feasible=True, clearance_m=250., chosen_pixel=dict(category='true_vehicle', confidence=.97))


class CaptureRecordingTests(unittest.TestCase):
    def test_every_nonempty_control_batch_is_recorded_without_half_second_gate(self):
        r = CaptureRecorder('a')
        cmd = [dict(verb='set_destination', params=dict(speed=32.))]
        d = diag(0.)
        for t in (0., .03, .1, .49):
            r.record(t, own(b'image'), d, cmd, source_digest=digest(b'image'))
        r.record(.5, own(b'image'), d, [], source_digest=digest(b'image'))
        cmd[0]['params']['speed'] = 99.
        d['capture']['phase'] = 'MUTATED'
        result = r.export()
        self.assertEqual([e['score_sim_s'] for e in result['control_events']], [0., .03, .1, .49])
        self.assertEqual(result['control_events'][0]['commands'][0]['params']['speed'], 32.)
        self.assertEqual(result['control_events'][0]['diagnostics']['capture']['phase'], 'SEARCH')

    def test_trigger_keeps_preceding_processed_sources_with_exact_receipt_pose(self):
        r = CaptureRecorder('a', recent_processed=3)
        first = b'first image bytes'
        second = b'second image bytes'
        r.record(0., own(first, pan=12.), diag(0.), [], source_digest=digest(first))
        # Inference of the first source is still current while the camera sees second.
        r.record(.5, own(second, pan=25.), diag(0.), [], source_digest=digest(first))
        r.record(1., own(b'third', pan=40.), diag(.5, 'VERIFY'), [], source_digest=digest(second))
        result = r.export()
        self.assertEqual(len(result['key_frames']), 2)
        self.assertEqual(result['key_frames'][1]['source_receipt_pose']['gimbal_pan'], 25.)
        self.assertIs(result['photo_bytes'][digest(first)], first)
        self.assertIs(result['photo_bytes'][digest(second)], second)
        self.assertFalse(result['key_frames'][1]['capture_pose_calibrated'])

    def test_nearest_pose_is_never_substituted_for_missing_exact_receipt(self):
        r = CaptureRecorder('a')
        photo = b'image'
        r.record(0., own(photo), diag(0.), [], source_digest=digest(photo))
        r.record(.5, own(photo, pan=30.), diag(.2, 'APPROACH'), [], source_digest=digest(photo))
        frame = r.export()['key_frames'][-1]
        self.assertEqual(frame['receipt_pose_status'], 'unknown_no_unique_exact_receipt')
        self.assertIsNone(frame['source_receipt_pose'])

    def test_retained_images_and_frames_cannot_exceed_count_or_byte_caps(self):
        r = CaptureRecorder('a', max_images=2, max_image_bytes=8, max_saved_frames=2,
                            recent_receipts=2, recent_processed=2)
        for i in range(10):
            photo = bytes([i])*4
            r.record(float(i), own(photo), diag(float(i), 'APPROACH'), [], source_digest=digest(photo))
        result = r.export()
        self.assertLessEqual(result['retained']['image_bytes'], 8)
        self.assertLessEqual(result['retained']['image_count'], 2)
        self.assertLessEqual(result['retained']['saved_frames'], 2)
        self.assertLessEqual(result['retained']['recent_receipts'], 2)
        self.assertGreater(result['dropped']['saved_frame_evicted_for_image_capacity'], 0)
        self.assertEqual([f['source_receipt_s'] for f in result['key_frames']], [8., 9.])
        self.assertIn(digest(bytes([9])*4), result['photo_bytes'])

    def test_late_capture_can_replace_early_verify_without_unbounding_images(self):
        r = CaptureRecorder('a', max_images=8, max_image_bytes=32, max_saved_frames=3,
                            recent_receipts=2, recent_processed=2)
        for i in range(12):
            phase = 'VERIFY' if i < 9 else 'APPROACH'
            photo = bytes([i])*4
            r.record(float(i), own(photo), diag(float(i),phase), [], source_digest=digest(photo))
        result = r.export()
        self.assertEqual([f['source_receipt_s'] for f in result['key_frames']], [9.,10.,11.])
        self.assertTrue(all(f['trigger_phase']=='APPROACH' for f in result['key_frames']))
        self.assertLessEqual(result['retained']['image_bytes'], 32)
        self.assertTrue(all(f['source_photo_sha256'] in result['photo_bytes'] for f in result['key_frames']))

    def test_event_count_and_byte_limits_are_independent_and_exposed(self):
        cmd = [dict(verb='set_speed', params=dict(speed=32.))]
        count = CaptureRecorder('a', max_events=1)
        byte = CaptureRecorder('a', max_event_bytes=1)
        for r in (count, byte):
            for t in (0., .1):
                r.record(t, own(None), {}, cmd)
        self.assertEqual(count.export()['retained']['events'], 1)
        self.assertEqual(count.export()['dropped']['event_count_capacity'], 1)
        self.assertEqual(byte.export()['retained']['events'], 0)
        self.assertEqual(byte.export()['dropped']['event_byte_capacity'], 2)

    def test_instances_are_private_and_reject_other_agent_and_rewind(self):
        a, b = CaptureRecorder('a'), CaptureRecorder('b')
        self.assertFalse(a.record(0., own(b'other', uid='b'), diag(0.), []))
        self.assertTrue(b.record(1., own(b'other', uid='b'), diag(1., 'VERIFY'), [], source_digest=digest(b'other')))
        self.assertFalse(b.record(.5, own(b'other', uid='b'), diag(.5), []))
        self.assertEqual(a.export()['retained']['image_count'], 0)
        self.assertEqual(b.export()['dropped']['invalid_or_rewound_time'], 1)
        self.assertEqual(a.export()['dropped']['wrong_agent'], 1)


if __name__ == '__main__':
    unittest.main()
