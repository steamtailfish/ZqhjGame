"""Recorder-only snapshots must be bounded, independent and JSON-safe."""
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from capture_geometry_recording import geometry_snapshot


@dataclass
class Box:
    x1: float = 10.
    y1: float = 20.
    x2: float = 30.
    y2: float = 40.


class GeometryRecordingTests(unittest.TestCase):
    def geometry(self):
        return SimpleNamespace(status='PLANE_ESTIMATED',
            last_pose=np.array([37., 121., 500., 0., 0., -80., 30.]),
            last_digest='source', last_time=10., size=(1024, 768),
            fit_center=np.array([37., 121.]), homography=np.eye(3), pair_old_digest='old',
            fits=deque([(8., 200., 1., 2.), (9., 202., 1.1, 2.2)]),
            history=deque([(8., np.zeros(7)), (8.5, np.ones(7)),
                           (10., np.full(7, 2.)), (10.1, np.full(7, 3.))]),
            locate=Mock(side_effect=AssertionError('Snapshot must not call locate')))

    def snapshot(self, geometry, **changes):
        args = dict(source_time=10., source_digest='source', box=Box(),
                    pixel_hits=3, enabled=True, geo_estimate=None)
        args.update(changes)
        return geometry_snapshot(geometry, **args)

    def test_json_values_are_plain_finite_and_none_is_legal(self):
        geometry = self.geometry()
        geometry.homography[0, 0] = np.nan
        geometry.fits.append((10., np.float64(200.), np.inf, np.int64(2)))
        result = self.snapshot(geometry, box=None)
        self.assertIsNone(result['box'])
        self.assertIsNone(result['geo_estimate'])
        self.assertIsNone(result['geometry']['homography'][0][0])
        self.assertIsNone(result['geometry']['fits'][-1][2])
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertIsInstance(result['geometry']['last_pose'], list)

    def test_snapshot_copies_arrays_deques_and_dataclass_without_mutation(self):
        geometry = self.geometry()
        box = Box()
        before_pose = geometry.last_pose.copy()
        result = self.snapshot(geometry, box=box, geo_estimate=Box(x1=50.))
        np.testing.assert_array_equal(geometry.last_pose, before_pose)
        self.assertEqual(len(geometry.fits), 2)
        geometry.last_pose[0] = 99.
        geometry.history[1][1][0] = 99.
        geometry.fit_center[0] = 99.
        geometry.homography[0, 0] = 99.
        geometry.fits.clear()
        box.x1 = 99.
        self.assertEqual(result['geometry']['last_pose'][0], 37.)
        self.assertEqual(result['geometry']['history_recent'][0][1][0], 1.)
        self.assertEqual(result['geometry']['fit_center'][0], 37.)
        self.assertEqual(result['geometry']['homography'][0][0], 1.)
        self.assertEqual(len(result['geometry']['fits']), 2)
        self.assertEqual(result['box']['x1'], 10.)
        self.assertEqual(result['geo_estimate']['x1'], 50.)

    def test_history_uses_source_window_and_both_collections_are_bounded(self):
        geometry = self.geometry()
        result = self.snapshot(geometry)
        self.assertEqual([item[0] for item in result['geometry']['history_recent']], [8.5, 10.])
        geometry.fits = [(float(i), 200., 1., 2.) for i in range(25)]
        geometry.history = [(9.+i*.001, np.zeros(7)) for i in range(200)]
        result = self.snapshot(geometry)
        self.assertEqual(len(result['geometry']['fits']), 10)
        self.assertEqual(result['geometry']['fits'][0][0], 15.)
        self.assertEqual(len(result['geometry']['history_recent']), 100)
        self.assertEqual(result['geometry']['history_recent'][0][0], 9.1)

    def test_precondition_is_recorded_without_calling_geometry(self):
        geometry = self.geometry()
        for enabled, hits, expected in ((True, 2, True), (True, 1, False), (False, 4, False)):
            result = self.snapshot(geometry, enabled=enabled, pixel_hits=hits)
            self.assertEqual(result['locate_called'], expected)
        geometry.locate.assert_not_called()
        result = self.snapshot(SimpleNamespace(), box=None, enabled=False, pixel_hits=0)
        self.assertIsNone(result['geometry']['fits'])
        self.assertIsNone(result['geometry']['last_pose'])
        self.assertFalse(result['locate_called'])


if __name__ == '__main__':
    unittest.main()
