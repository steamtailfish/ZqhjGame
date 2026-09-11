"""Learning/export contract tests, including parity with stdlib online inference."""
import math
import unittest

import torch

from learning.dataset import scene_from_records
from learning.guidance import GuidancePolicy, trajectory_cost, rollout
from zqhj_features import FEATURE_DIM, FEATURE_VERSION, body_vector, feature_vector, planning_record
from zqhj_inference import EmbeddedPolicy, LearnedPlanner, check_control
from zqhj_planner import Circle, PeerMotion, PrimitivePlanner


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.record = planning_record((10.,20.),73.,22.,90.,
            peers=(PeerMotion(900,500,12,7,.5),),bounds=(-1000,1000,-1200,1200),
            obstacles=(Circle(400,200,30),),target=(300,700))

    def test_features_match_training_at_arbitrary_heading(self):
        scene = scene_from_records([self.record])
        expected = torch.tensor(feature_vector(self.record))
        self.assertEqual(expected.numel(),FEATURE_DIM)
        torch.testing.assert_close(scene.features()[0],expected,rtol=1e-6,atol=1e-7)

    def test_rotated_boundary_distance_is_world_distance(self):
        record = planning_record((10,20),90,22,90,bounds=(-100,100,-200,200))
        x,y = body_vector(5,-7,90)
        distances = [nx*x+ny*y+b for nx,ny,b in record['boundary']]
        for a,b in zip(distances,(115,85,213,187)):
            self.assertAlmostEqual(a,b)

    def test_stdlib_network_matches_torch(self):
        torch.manual_seed(83)
        model = GuidancePolicy().eval()
        embedded = EmbeddedPolicy(FEATURE_VERSION,{k:v.tolist() for k,v in model.state_dict().items()})
        controls,scores = embedded.predict(self.record)
        with torch.no_grad():
            expected_controls,expected_scores = model(scene_from_records([self.record]).features())
        torch.testing.assert_close(torch.tensor(controls),expected_controls[0],rtol=1e-5,atol=1e-6)
        torch.testing.assert_close(torch.tensor(scores),expected_scores[0],rtol=1e-5,atol=1e-6)

    def test_rollout_matches_exact_online_check_in_world_frame(self):
        control = (.12,.7)
        path,_ = check_control((10,20),73,22,control)
        tensor_path,_,_ = rollout(torch.tensor([22.],dtype=torch.float64),torch.tensor([[control]],dtype=torch.float64))
        for actual,body in zip(path,tensor_path[0,0].tolist()):
            # Inverse body transform, expressed as a rotation by -heading.
            dx,dy = body_vector(*body,-73)
            self.assertAlmostEqual(actual[1],10+dx,places=9)
            self.assertAlmostEqual(actual[2],20+dy,places=9)

    def test_boundary_cost_gradient_matches_difference(self):
        scene = scene_from_records([self.record])
        for name in scene.__dataclass_fields__:
            setattr(scene,name,getattr(scene,name).double())
        scene.boundary[:,:,2] = 130.
        controls = torch.tensor([[[.07,.31]]],dtype=torch.float64,requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(lambda u:trajectory_cost(scene,u)[0],(controls,),
                                                eps=1e-5,atol=1e-4,rtol=1e-3))

    def test_neural_infeasibility_and_failure_use_analytic_fallback(self):
        class BadPolicy:
            def predict(self,record):raise ValueError('test failure')
        planner = LearnedPlanner(BadPolicy(),PrimitivePlanner())
        result = planner.plan((0,0),0,22,0)
        self.assertTrue(result.feasible)
        self.assertEqual(planner.fallback_count,1)
        class StraightPolicy:
            def predict(self,record):return [(0.,0.)],[100.]
        planner = LearnedPlanner(StraightPolicy(),PrimitivePlanner())
        result = planner.plan((0,0),0,22,0,peers=(PeerMotion(1,0,0,22),))
        self.assertEqual(planner.fallback_count,1)
        self.assertFalse(result.feasible)

    def test_safe_neural_action_is_used_and_all_obstacles_are_checked(self):
        class StraightPolicy:
            def predict(self,record):return [(0.,0.)],[10.]
        planner = LearnedPlanner(StraightPolicy(),PrimitivePlanner())
        self.assertEqual(planner.plan((0,0),0,22,0).reason,'neural_with_swept_check')
        obstacles = tuple(Circle(1000+i,1000,1) for i in range(4))+(Circle(0,44,5),)
        _,margin = check_control((0,0),0,22,(0,0),obstacles=obstacles)
        self.assertLess(margin,0)

    def test_checkpoint_shape_and_version_rejected(self):
        with self.assertRaises(ValueError):EmbeddedPolicy('old',{})
        with self.assertRaises(ValueError):EmbeddedPolicy(FEATURE_VERSION,{})

    def test_bad_score_cannot_select_safe_circle_over_straight_progress(self):
        class MisrankedPolicy:
            def predict(self,record):return [(math.pi/6,0.),(0.,0.)],[100.,-100.]
        planner=LearnedPlanner(MisrankedPolicy(),PrimitivePlanner())
        result=planner.plan((0.,0.),0.,22.,0.)
        self.assertEqual(result.heading,0.)
        self.assertEqual(planner.selected_count,1)
        class CircleOnly:
            def predict(self,record):return [(math.pi/6,0.)],[100.]
        planner=LearnedPlanner(CircleOnly(),PrimitivePlanner())
        self.assertEqual(planner.plan((0.,0.),0.,22.,0.).heading,0.)
        self.assertEqual(planner.last_source,'neural_guide_quality_rejected')


if __name__ == '__main__':
    unittest.main()
