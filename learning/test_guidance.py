"""Run in the optional learning environment, not the stdlib-only agent tests."""
import math
import unittest

import torch

from learning.guidance import GuidancePolicy, guidance_loss, rollout, synthetic_scene, trajectory_cost


class GuidanceTests(unittest.TestCase):
    def test_cost_gradient_matches_finite_difference(self):
        scene = synthetic_scene(2,7,dtype=torch.float64)
        controls = torch.tensor([[[.07,.31],[-.09,-.22]],[[.05,.17],[-.08,-.27]]],
                                dtype=torch.float64,requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(lambda u:trajectory_cost(scene,u)[0],
                                                (controls,),eps=1e-5,atol=1e-4,rtol=1e-3))

    def test_trajectory_cost_updates_offset_head(self):
        torch.manual_seed(11)
        model = GuidancePolicy()
        result = guidance_loss(model,synthetic_scene(4,17))
        result['trajectory_loss'].backward()
        self.assertGreater(model.offset_head.weight.grad.norm().item(),0)
        self.assertTrue(torch.isfinite(model.offset_head.weight.grad).all())
        self.assertIsNone(model.score_head.weight.grad)

    def test_score_target_does_not_backprop_into_trajectory_head(self):
        model = GuidancePolicy()
        result = guidance_loss(model,synthetic_scene(4,8))
        result['score_loss'].backward()
        self.assertIsNone(model.offset_head.weight.grad)
        self.assertGreater(model.score_head.weight.grad.norm().item(),0)

    def test_all_rejected_batch_is_finite_zero_trajectory_gradient(self):
        model = GuidancePolicy()
        result = guidance_loss(model,synthetic_scene(2,5),max_cost=-1.)
        self.assertEqual(result['trajectory_loss'].item(),0.)
        result['trajectory_loss'].backward()
        self.assertEqual(model.offset_head.weight.grad.norm().item(),0.)
        self.assertTrue(torch.isfinite(result['loss']))

    def test_bounded_controls_and_speed_acceleration(self):
        model = GuidancePolicy()
        controls,_ = model(synthetic_scene(4,2).features()*100)
        self.assertTrue((controls[...,0].abs() <= math.radians(30)+1e-6).all())
        self.assertTrue((controls[...,1].abs() <= 5+1e-6).all())
        _,speeds,accelerations = rollout(torch.tensor([15.,16.,39.,40.]),controls)
        self.assertTrue(((speeds >= 15)&(speeds <= 40)).all())
        self.assertTrue((accelerations.abs() <= 5+1e-5).all())

    def test_absent_geometry_is_masked_and_no_obstacle_is_invented(self):
        scene = synthetic_scene(2,2)
        scene.obstacle_mask.zero_()
        scene.peer_mask.zero_()
        controls = torch.zeros(2,1,2)
        first = trajectory_cost(scene,controls)[0]
        self.assertEqual(trajectory_cost(scene,controls)[1]['safety'].sum().item(),0.)
        scene.obstacles.fill_(100000.)
        scene.peers.fill_(100000.)
        self.assertTrue(torch.equal(first,trajectory_cost(scene,controls)[0]))
        self.assertTrue((scene.features()[:,7:] == 0).all())

    def test_reject_invalid_scene(self):
        scene = synthetic_scene(1,1)
        scene.speed[0] = 0
        with self.assertRaises(ValueError):
            scene.validate()

    def test_small_optimization_reduces_same_batch_cost(self):
        torch.manual_seed(19)
        model,scene = GuidancePolicy(),synthetic_scene(8,29)
        optimizer = torch.optim.Adam(model.parameters(),lr=.002)
        initial = guidance_loss(model,scene)['trajectory_loss'].item()
        for _ in range(12):
            optimizer.zero_grad(set_to_none=True)
            loss = guidance_loss(model,scene)['trajectory_loss']
            loss.backward()
            optimizer.step()
        self.assertLess(guidance_loss(model,scene)['trajectory_loss'].item(),initial)


if __name__ == '__main__':
    unittest.main()
