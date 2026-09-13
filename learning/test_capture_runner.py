"""Full recorder-wrapper integration with an in-memory official-run substitute."""
import builtins
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT/'tools'))
import vision_runner


FAKE_AGENT = '''
import hashlib
from types import SimpleNamespace as NS

class EntryAgent:
    def __init__(self, my_uid):
        self.my_uid = my_uid
        self.enable_geometry = True
        self.detector = NS(size=64, confidence=.9, names=('true_vehicle','decoy_vehicle'))
        self.photo_digest = None
        self.photo_time = None
        self.boxes = []
        self.pixel_target = None
        self.pixel_hits = 2
        self.geo_estimate = None
        self.geometry = NS(status='TEST', history=[], fits=[])
        self.closed = False

    def decide(self, obs, dt):
        t = obs.briefing.score_view.sim_time
        if t != .2:
            self.photo_digest = hashlib.sha256(obs.self.photo).hexdigest()
            self.photo_time = t
        phase = 'VERIFY' if t == .2 else 'APPROACH' if .2 < t < .6 else 'SEARCH'
        self.diagnostics = dict(receipt_first_seen_sim_s=self.photo_time,
            plan_feasible=True, clearance_m=250.,
            capture=dict(phase=phase, owner=self.my_uid, partner='b', mission=1))
        self.geometry.history = [(t, {'gimbal_pan': obs.self.gimbal_pan})]
        self.last_commands = [NS(verb='set_destination', params={'speed': 20+t, 'latitude': 27., 'longitude': 125.})]
        return self.last_commands

    def close_detector(self):
        self.closed = True
'''


@dataclass
class Stats:
    sent: int = 0


class CaptureRunnerIntegrationTests(unittest.TestCase):
    def test_full_wrapper_retains_controls_geometry_and_source_images_without_callback_io(self):
        archive = PROJECT/'.local-archive'
        archive.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='capture-runner-test-', dir=archive) as temporary:
            root = Path(temporary)
            package, output = root/'submission', root/'run'
            package.mkdir()
            output.mkdir()
            agent_path, weight_path = package/'agent.py', package/'vision.pt'
            agent_path.write_text(FAKE_AGENT, encoding='utf-8')
            weight_path.write_bytes(b'fake weights: never load a model')
            before = {p: p.read_bytes() for p in (agent_path, weight_path)}
            callbacks, instances = [], []
            times = (0., .1, .2, .3, .4, .6)
            photos = {t: f'public photo at {t}'.encode() for t in times}

            def guarded_open(original):
                def call(file, mode='r', *args, **kwargs):
                    if any(flag in mode for flag in 'wax+'):
                        raise AssertionError('filesystem write during callback')
                    return original(file, mode, *args, **kwargs)
                return call

            def guarded_os_open(path, flags, *args, **kwargs):
                if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                    raise AssertionError('os filesystem write during callback')
                return real_os_open(path, flags, *args, **kwargs)

            real_os_open = os.open
            def fake_run(agent_class, **kwargs):
                self.assertEqual(kwargs['duration'], 1.)
                self.assertTrue(kwargs['start_sim'])  # intercepted here; never starts a process
                instance = agent_class('a')
                instances.append(instance)
                for t in times:
                    obs = SimpleNamespace(self=SimpleNamespace(uid='a', photo=photos[t], lat=27., lon=125.,
                        alt=500., heading_deg=90., speed=32., gimbal_pan=t*100, gimbal_tilt=-45.,
                        gimbal_fov_deg=30., status='active', comm_stats=Stats()), comm_inbox=[],
                        briefing=SimpleNamespace(score_view=SimpleNamespace(sim_time=t), params={}, mission_area=None))
                    with patch('builtins.open', guarded_open(builtins.open)), \
                         patch('io.open', guarded_open(io.open)), \
                         patch('os.open', guarded_os_open), \
                         patch.object(Path, 'mkdir', side_effect=AssertionError('mkdir during callback')):
                        returned = instance.decide(obs, .1)
                    self.assertIs(returned, instance.last_commands)
                    callbacks.append([dict(verb=c.verb, params=dict(c.params)) for c in returned])
                    self.assertFalse((output/'observations').exists())

            modules = {}
            for name in ('competition', 'competition.sdk', 'competition.sdk.scenarios',
                         'competition.sdk.scenarios.coop_decoy', 'competition.sdk.scenarios.coop_decoy.runner'):
                modules[name] = ModuleType(name)
                modules[name].__path__ = []
            modules['competition.sdk.scenarios.coop_decoy.runner'].run = fake_run
            for name, fields in (
                ('zqhj_photo_entry', ('PhotoEntryAgent',)),
                ('zqhj_inference', ('EmbeddedPolicy', 'LearnedPlanner')),
                ('zqhj_planner', ('PrimitivePlanner',))):
                module = modules[name] = ModuleType(name)
                for field in fields:
                    setattr(module, field, type(field, (), {}))
            args = SimpleNamespace(submission=agent_path, geometry=None, enable_reports=False,
                duration=1., max_photos=1, sim_root=root/'unused-simulator', output=output,
                seed=102, image_size=64, confidence=.9)
            with patch.dict(sys.modules, modules), patch.object(sys, 'dont_write_bytecode', True):
                vision_runner.run_photo_worker(args)

            folder = output/'observations'/'a'
            read_rows = lambda name: [json.loads(line) for line in (folder/name).read_text().splitlines()]
            controls = read_rows('control-events.jsonl')
            sparse = read_rows('observations.jsonl')
            geometry = read_rows('geometry-inputs.jsonl')
            capture = json.loads((folder/'capture-recording.json').read_text())
            self.assertEqual([r['score_sim_s'] for r in controls], list(times))
            self.assertEqual([r['commands'] for r in controls], callbacks)
            self.assertEqual([r['score_sim_s'] for r in sparse], [0., .6])
            self.assertEqual([r['source_receipt_sim_s'] for r in geometry], [0., .1, .3, .4, .6])
            self.assertEqual([r['recorded_at_s'] for r in geometry], [0., .1, .3, .4, .6])
            self.assertEqual(capture['geometry_records'], 5)
            self.assertEqual(capture['wrapper_dropped'], {})
            self.assertTrue(instances[0].closed)
            # Sparse max_photos=1 only keeps t=0; the key-phase recorder adds .1/.3/.4.
            for t in (0., .1, .3, .4):
                digest = hashlib.sha256(photos[t]).hexdigest()
                self.assertEqual((folder/(digest+'.image')).read_bytes(), photos[t])
            keys = capture['key_frames']
            first_source = next(k for k in keys if k['source_receipt_s'] == .1)
            self.assertEqual(first_source['trigger_phase'], 'VERIFY')
            self.assertEqual(first_source['source_receipt_pose']['gimbal_pan'], 10.)
            self.assertEqual(first_source['receipt_pose_status'], 'exact_receipt_time_and_digest_match')
            self.assertFalse(first_source['capture_pose_calibrated'])
            for path, original in before.items():
                self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
