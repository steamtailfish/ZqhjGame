"""Broad public-area search; visual rendezvous and reporting remain gated."""
import math
from zqhj_team import TeamPhotoEntryAgent
from zqhj_photo_entry import PhotoEntryAgent


class ScoreSearchAgent(TeamPhotoEntryAgent):
    report_min_hits=4
    report_uncertainty_limit=110.
    identity_confidence=.65
    identity_margin=.35
    # Accuracy reports are legal independently of the K=2 capture assignment.
    independent_reports=True
    require_report_motion=True
    require_candidate_motion=True
    fast_pixel_reports=True
    report_from_geo_bank=False
    fast_report_identity_hits=3
    fast_report_uncertainty_limit=110.

    def reset(self):
        super().reset()
        self.coverage.spacing=280.

    def search_goal(self,position,bounds):
        self.search_focus=None;self.follow_slot=None;self.follow_velocity=None
        return self.coverage.goal(position,bounds,self.radio.peers)

    def prepare_planner(self,own,target,formation,position):
        self.planner.cruise_speed=(32. if math.dist(position,target)>750 else 22.) if formation else 35.

    def camera_fov(self,own,formation):return 50.

    def aim_gimbal(self,own,now,pan,tilt,formation=False):
        if formation:desired=super().aim_gimbal(own,now,pan,tilt,formation=True)
        else:desired=PhotoEntryAgent.aim_gimbal(self,own,now,pan,tilt)
        # Camera receipt pose is not a verified image-capture pose. Small
        # commands limit lag-induced overcorrection and keep image overlap.
        delta=(desired[0]-own.gimbal_pan+180)%360-180
        return ((own.gimbal_pan+max(-6.,min(6.,delta))+180)%360-180,
                own.gimbal_tilt+max(-3.,min(3.,desired[1]-own.gimbal_tilt)))

    def decide(self,obs,dt):
        commands=super().decide(obs,dt)
        self.diagnostics['strategy']='distributed_search_then_rendezvous'
        return commands
