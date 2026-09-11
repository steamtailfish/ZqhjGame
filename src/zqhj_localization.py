"""Public-photo localization primitives; standard library, no I/O or hidden state."""
from dataclasses import dataclass, asdict
import hashlib
import math


class ObservationClock:
    """Keep the public episode time unchanged. Local reset numbers are NOT TTL epochs."""
    def __init__(self, max_gap_s=1.0):
        self.max_gap_s = max_gap_s
        self.reset()

    def reset(self):
        self.previous = None
        self.digest = None
        self.first_seen_sim = None
        self.first_seen_wall = None

    def update(self, sim_s, photo, wall_s):
        reasons = []
        if sim_s is None or not math.isfinite(sim_s) or sim_s < 0:
            reasons.append('observation_time_missing_or_invalid')
            sim_s = None
        delta = None if sim_s is None or self.previous is None else sim_s-self.previous
        if delta is not None:
            if delta < 0:
                reasons.append('time_rewound')
                self.digest = None
            elif delta == 0: reasons.append('duplicate_observation_time')
            elif delta > self.max_gap_s: reasons.append('observation_time_gap')
        digest = hashlib.sha256(photo).hexdigest() if photo else None
        changed = digest is not None and digest != self.digest
        if changed:
            self.first_seen_sim, self.first_seen_wall = sim_s, wall_s
        if photo is None or not photo:
            reasons.append('photo_missing')
            self.first_seen_sim = self.first_seen_wall = None
        elif not changed:
            reasons.append('same_photo_bytes')
        if sim_s is not None: self.previous = sim_s
        self.digest = digest
        return dict(observation_sim_s=sim_s, elapsed_sim_s=delta,
            receipt_first_seen_sim_s=self.first_seen_sim, receipt_first_seen_wall_s=self.first_seen_wall,
            observation_wall_s=wall_s, capture_sim_s=None, capture_wall_s=None,
            photo_sha256=digest, new_photo_bytes=changed, accept_new_sample=not reasons,
            reasons=reasons, clock_domain='official_episode_relative_sim_seconds',
            cross_agent_ttl='requires same official episode; never subtract per-agent reset origins')


@dataclass(frozen=True)
class CandidatePixel:
    source: str
    source_detail: str
    u: float
    v: float
    image_width: int
    image_height: int
    image_sha256: str
    uid: str


def camera_basis(pan_deg, tilt_deg, heading_deg, yaw_convention):
    if yaw_convention not in ('world_pan', 'heading_plus_pan'):
        raise ValueError('yaw_convention_unconfirmed')
    yaw = math.radians(pan_deg+(heading_deg if yaw_convention == 'heading_plus_pan' else 0))
    pitch = math.radians(tilt_deg)
    # ENU: east, north, up; image u right, v down, no camera roll.
    forward = (math.cos(pitch)*math.sin(yaw), math.cos(pitch)*math.cos(yaw), math.sin(pitch))
    right = (math.cos(yaw), -math.sin(yaw), 0.0)
    down = (math.sin(pitch)*math.sin(yaw), math.sin(pitch)*math.cos(yaw), -math.cos(pitch))
    return forward, right, down


def pixel_ray(u, v, width, height, fov_deg, fov_axis, pan, tilt, heading, yaw_convention):
    if fov_axis not in ('horizontal','vertical'): raise ValueError('fov_axis_unconfirmed')
    if not 0 < fov_deg < 179: raise ValueError('fov_invalid')
    focal = (width if fov_axis == 'horizontal' else height)/(2*math.tan(math.radians(fov_deg)/2))
    # Pixel centers use integer indices 0..W-1. Uncropped, square-pixel model.
    x, y = (u-(width-1)/2)/focal, (v-(height-1)/2)/focal
    forward, right, down = camera_basis(pan,tilt,heading,yaw_convention)
    ray = tuple(forward[i]+x*right[i]+y*down[i] for i in range(3))
    norm = math.sqrt(sum(c*c for c in ray))
    return tuple(c/norm for c in ray)


def project_candidate(candidate, own, timing, *, fov_axis, yaw_convention,
                      ground_alt_m, height_source, calibration_evidence,
                      stable_pose, uncropped, offline=False, max_range_m=3000):
    """Conditional local-plane estimate. valid means the DECLARED model passes guards.

    No auto-default ground altitude, FOV axis, heading convention or frame timestamp.
    Unknown capture pose is a hard online rejection. Offline use must retain limits.
    """
    result = dict(candidate=asdict(candidate), time=timing, position_valid=False,
        validity_scope='declared_offline_model_only' if offline else 'online_capture_aligned_model',
        temporal_alignment_verified=bool(timing.get('capture_pose_verified') and
            timing.get('capture_sim_s') is not None and timing.get('pose_sim_s')==timing.get('capture_sim_s')),
        latitude=None, longitude=None, local_east_m=None, local_north_m=None,
        absolute_accuracy_verified=False, online_usable=False, invalid_reasons=[], quality_limits=[],
        assumptions=dict(fov_axis=fov_axis,yaw_convention=yaw_convention,
            pixel_axes='u right/v down; integer pixel centers',square_pixels=True,camera_roll_deg=0,
            ground_alt_m=ground_alt_m,height_source=height_source,
            calibration_evidence=calibration_evidence,uncropped=uncropped,
            mode='offline_conditional_geometry' if offline else 'online'))
    reasons=result['invalid_reasons']
    if candidate.uid != own.get('uid'):reasons.append('candidate_uid_mismatch')
    if candidate.image_sha256 != timing.get('photo_sha256'):reasons.append('candidate_photo_mismatch')
    if candidate.source not in ('offline_manual_photo','offline_template_correspondence','online_photo_detector'):
        reasons.append('candidate_source_unsupported')
    if not offline and candidate.source != 'online_photo_detector':reasons.append('offline_annotation_forbidden_online')
    if not candidate.source_detail:reasons.append('candidate_provenance_missing')
    values=[candidate.u,candidate.v,own.get('lat'),own.get('lon'),own.get('alt'),
            own.get('heading_deg'),own.get('gimbal_pan'),own.get('gimbal_tilt'),own.get('gimbal_fov_deg')]
    if any(x is None or not isinstance(x,(float,int)) or not math.isfinite(x) for x in values):
        reasons.append('nonfinite_geometry')
        return result
    if candidate.image_width <= 1 or candidate.image_height <= 1:reasons.append('image_size_invalid')
    if not (0 <= candidate.u < candidate.image_width and 0 <= candidate.v < candidate.image_height):
        reasons.append('pixel_outside_image')
    if not uncropped:reasons.append('unknown_crop_or_resize')
    if not stable_pose:reasons.append('pose_not_stable')
    if not calibration_evidence:reasons.append('calibration_evidence_missing')
    if ground_alt_m is None or not math.isfinite(ground_alt_m) or not height_source:
        reasons.append('ground_height_datum_unknown')
    if timing.get('observation_sim_s') is None:reasons.append('observation_time_missing')
    reasons.extend(timing.get('reasons',[]))
    if timing.get('capture_sim_s') is None:
        if offline:result['quality_limits'].append('capture_time_unknown; receipt_pose_is_a_conditional_approximation')
        else:reasons.append('capture_pose_alignment_unverified')
    elif not offline:
        capture=timing['capture_sim_s']
        pose_time=timing.get('pose_sim_s')
        if (not isinstance(capture,(float,int)) or not math.isfinite(capture)
                or not timing.get('capture_pose_verified') or pose_time!=capture):
            reasons.append('capture_pose_alignment_unverified')
    if reasons:return result
    if not -90 <= own['lat'] <= 90 or not -180 <= own['lon'] <= 180:
        reasons.append('geographic_coordinate_invalid');return result
    if abs(own['lat']) > 85:
        reasons.append('local_geographic_approximation_near_pole');return result
    if not -90 <= own['gimbal_tilt'] <= 90:
        reasons.append('tilt_outside_supported_model');return result
    try:
        ray=pixel_ray(candidate.u,candidate.v,candidate.image_width,candidate.image_height,
            own['gimbal_fov_deg'],fov_axis,own['gimbal_pan'],own['gimbal_tilt'],own['heading_deg'],yaw_convention)
    except ValueError as exc:
        reasons.append(str(exc));return result
    result['ray_enu']=ray
    height=own['alt']-ground_alt_m
    if height <= 0:reasons.append('camera_not_above_ground');return result
    if ray[2] >= -.1:reasons.append('ray_upward_or_near_horizon');return result
    distance=height/-ray[2]
    east,north=ray[0]*distance,ray[1]*distance
    if math.hypot(east,north)>max_range_m:
        reasons.append('projection_range_exceeded');return result
    result.update(position_valid=True,latitude=own['lat']+north/111320,
        longitude=own['lon']+east/(111320*math.cos(math.radians(own['lat']))),
        local_east_m=east,local_north_m=north,slant_range_m=distance,
        online_usable=not offline)
    result['quality_limits'] += ['local_plane_not_hidden_terrain','height_datum_and_zero_roll_are_explicit_model_assumptions',
                                 'no_independent_absolute_position_reference; no calibrated_probability']
    return result
