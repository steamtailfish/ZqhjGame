"""Physical orbit and safety checks for v31; never starts the simulator.

The 20s reference integrates commanded constant yaw rate and speed change at
5ms resolution, independently of the planner's 250ms path discretization.
It is an ideal commanded-dynamics check, not a fly_to/engine tracking guarantee.
"""
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT.parent)]
from zqhj_capture import CaptureSearchAgent, APPROACH, OFFER, TRACK, RECOVER, RELEASE
from zqhj_planner import Circle, PeerMotion, PrimitivePlanner, guide_heading
from zqhj_state import LocalFrame, wrap


def advance_physical(position, heading, speed, plan, duration=.5):
    """Integrate a planar vehicle from command endpoints without reading plan.path."""
    delta_heading = wrap(plan.heading-heading)
    x, y = position
    steps = 100
    for i in range(steps):
        fraction = (i+.5)/steps
        angle = math.radians(heading+fraction*delta_heading)
        velocity = speed+fraction*(plan.speed-speed)
        x += velocity*math.sin(angle)*duration/steps
        y += velocity*math.cos(angle)*duration/steps
    return (x, y), plan.heading, plan.speed


def dense_path(path):
    """Independent interpolation to test geometrical separation along each chord."""
    for a, b in zip(path, path[1:]):
        for k in range(11):
            fraction = k/10
            yield tuple(a[i]+fraction*(b[i]-a[i]) for i in range(3))


class CaptureOrbitTests(unittest.TestCase):
    def planner(self, enabled=True):
        planner = PrimitivePlanner()
        planner.orbit_guidance_enabled = enabled
        planner.cruise_speed = 18.
        return planner

    def test_static_orbit_selects_physical_negative_curvature_at_both_radii_and_rotations(self):
        for radius in (320., 360.):
            for angle in (0., math.pi/3, -math.pi/2):
                with self.subTest(radius=radius, angle=angle):
                    target = (750., -320.)
                    position = (target[0]+radius*math.cos(angle), target[1]+radius*math.sin(angle))
                    heading = -math.degrees(angle) % 360
                    plan = self.planner().plan(position, heading, 18., heading, target=target, radius=radius)
                    actual_rate = wrap(plan.heading-heading)/.5
                    self.assertTrue(plan.feasible)
                    self.assertLess(actual_rate, 0.)
                    # Classical uniform circular-motion reference, not the planner cost.
                    self.assertAlmostEqual(actual_rate, -math.degrees(18./radius), places=6)
                    self.assertAlmostEqual(plan.speed, 18., places=6)

    def test_twenty_second_ideal_receding_orbit_preserves_radius_speed_and_direction(self):
        for radius in (320., 360.):
            with self.subTest(radius=radius):
                planner = self.planner()
                position, heading, speed = (radius, 0.), 0., 18.
                largest_error = 0.
                angles = [0.]
                for _ in range(40):
                    velocity = (speed*math.sin(math.radians(heading)), speed*math.cos(math.radians(heading)))
                    desired = guide_heading(position, velocity, (0., 0.), radius=radius, formation=True)
                    plan = planner.plan(position, heading, speed, desired, target=(0., 0.), radius=radius)
                    self.assertTrue(plan.feasible)
                    self.assertLess(wrap(plan.heading-heading), 0.)
                    position, heading, speed = advance_physical(position, heading, speed, plan)
                    largest_error = max(largest_error, abs(math.hypot(*position)-radius))
                    angles.append(math.atan2(position[1], position[0]))
                    self.assertAlmostEqual(speed, 18., places=6)
                self.assertLess(largest_error, .1)  # metres; far tighter than the 60m entry band
                self.assertTrue(all(b > a for a, b in zip(angles, angles[1:])))
                self.assertAlmostEqual(angles[-1], 18.*20/radius, delta=.001)

    def test_default_off_far_and_no_target_retain_legacy_result(self):
        default = PrimitivePlanner()
        default.cruise_speed = 18.
        off = self.planner(False)
        arguments = ((320., 0.), 0., 18., 0.)
        self.assertFalse(default.orbit_guidance_enabled)
        self.assertEqual(default.plan(*arguments, target=(0., 0.), radius=320.),
                         off.plan(*arguments, target=(0., 0.), radius=320.))
        for position, target in (((380.001, 0.), (0., 0.)),
                                 ((259.999, 0.), (0., 0.)), ((320., 0.), None)):
            with self.subTest(position=position, target=target):
                enabled = self.planner(True)
                expected = off.plan(position, 0., 18., 0., target=target, radius=320.)
                actual = enabled.plan(position, 0., 18., 0., target=target, radius=320.)
                self.assertEqual(actual, expected)
                self.assertEqual(enabled.last_goal_mode, 'straight')

    def agent_shell(self, uid='owner', phase=APPROACH):
        # prepare_planner/navigation_commands need no detector or simulator state.
        a = object.__new__(CaptureSearchAgent)
        a.my_uid = uid
        a.planner = self.planner(False)
        a.capture = SimpleNamespace(mission=SimpleNamespace(owner='owner', partner='partner'), phase=phase)
        return a

    def test_capture_gate_is_member_only_and_resets_on_every_planning_call(self):
        own = SimpleNamespace()
        for uid in ('owner', 'partner'):
            for phase in (OFFER, APPROACH, TRACK, RECOVER):
                with self.subTest(uid=uid, phase=phase):
                    a = self.agent_shell(uid, phase)
                    a.prepare_planner(own, (0., 0.), True, (360., 0.))
                    self.assertTrue(a.planner.orbit_guidance_enabled)
                    a.prepare_planner(own, None, False, (360., 0.))
                    self.assertFalse(a.planner.orbit_guidance_enabled)
        for uid, phase, distance in (('third', APPROACH, 360.), ('partner', RELEASE, 360.),
                                      ('owner', RELEASE, 320.), ('partner', APPROACH, 411.)):
            with self.subTest(uid=uid, phase=phase, distance=distance):
                a = self.agent_shell(uid, phase)
                a.planner.orbit_guidance_enabled = True  # detect stale enabled state
                a.prepare_planner(own, (0., 0.), True, (distance, 0.))
                self.assertFalse(a.planner.orbit_guidance_enabled)
        a = self.agent_shell()
        a.capture.mission = None
        a.planner.orbit_guidance_enabled = True
        a.prepare_planner(own, (0., 0.), True, (320., 0.))
        self.assertFalse(a.planner.orbit_guidance_enabled)

    def test_safety_can_override_orbit_for_boundary_obstacle_and_peer(self):
        cases = (
            dict(bounds=(-1000., 1000., -1000., 165.)),
            dict(obstacles=(Circle(305., 145., 30.),)),
            dict(peers=(PeerMotion(-80., 180., 0., 0., 0.),)),
        )
        nominal = self.planner().plan((320., 0.), 0., 18., 0., target=(0., 0.), radius=320.)
        for constraints in cases:
            with self.subTest(constraints=constraints):
                plan = self.planner().plan((320., 0.), 0., 18., 0., target=(0., 0.), radius=320., **constraints)
                self.assertTrue(plan.feasible)
                self.assertGreaterEqual(plan.clearance_m, 0.)
                self.assertNotEqual(plan.heading, nominal.heading)
                self.assertLessEqual(abs(wrap(plan.heading)), 30.*.5+1e-8)
                self.assertLessEqual(abs(plan.speed-18.), 5.*.5+1e-8)
                for t, x, y in dense_path(plan.path):
                    if 'bounds' in constraints:
                        xmin, xmax, ymin, ymax = constraints['bounds']
                        self.assertGreaterEqual(min(x-xmin, xmax-x, y-ymin, ymax-y), 101.-1e-6)
                    for obstacle in constraints.get('obstacles', ()):
                        self.assertGreaterEqual(math.hypot(x-obstacle.x, y-obstacle.y), obstacle.radius+51.-1e-6)
                    for peer in constraints.get('peers', ()):
                        distance = math.hypot(x-peer.x-peer.vx*t, y-peer.y-peer.vy*t)
                        self.assertGreaterEqual(distance, 223.+40*peer.age_s+13*t*t-1e-6)

    def test_unavoidable_peer_overlap_is_reported_infeasible_not_overruled_by_orbit(self):
        plan = self.planner().plan((320., 0.), 0., 18., 0., target=(0., 0.), radius=320.,
                                   peers=(PeerMotion(320., 0., 0., 0.),))
        self.assertFalse(plan.feasible)
        self.assertLess(plan.clearance_m, 0.)
        self.assertEqual(plan.reason, 'no_feasible_primitive')

    def test_fly_to_preserves_planned_first_heading_and_speed_as_300m_waypoint(self):
        frame = LocalFrame(27., 125.)
        position = (320., 0.)
        lat, lon = frame.geo(*position)
        own = SimpleNamespace(lat=lat, lon=lon)
        a = self.agent_shell()
        plan = self.planner().plan(position, 0., 18., 0., target=(0., 0.), radius=320.)
        commands = a.navigation_commands(own, plan, frame)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].verb, 'set_destination')
        params = commands[0].params
        waypoint = frame.xy(params['latitude'], params['longitude'])
        bearing = math.degrees(math.atan2(waypoint[0]-position[0], waypoint[1]-position[1]))
        self.assertAlmostEqual(math.dist(position, waypoint), 300., places=5)
        self.assertAlmostEqual(wrap(bearing-plan.heading), 0., places=5)
        self.assertEqual(params['speed'], plan.speed)
        self.assertEqual(params['loiter_radius'], 0.)


if __name__ == '__main__':
    unittest.main()
