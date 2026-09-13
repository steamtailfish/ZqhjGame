"""Small read-only snapshots for a recorder; no policy or geometry execution."""
from collections import deque
from dataclasses import asdict, is_dataclass
import math


def _plain(value):
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if hasattr(value, 'tolist'):
        return _plain(value.tolist())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise TypeError(f'Unsupported snapshot value: {type(value).__name__}')


def _bounded(value, count):
    return None if value is None else list(deque(value, maxlen=count))


def geometry_snapshot(geometry, *, source_time, source_digest, box, pixel_hits,
                      enabled, geo_estimate):
    """Copy locate inputs and its recorded result without calling locate.

    ``locate_called`` records the sensor's enabled/hit precondition, not an
    observed function-call trace. Nonfinite diagnostic values become null.
    Arrays and nested containers are copied, never retained by reference.
    """
    fits = _bounded(getattr(geometry, 'fits', None), 10)
    history = _bounded(getattr(geometry, 'history', None), 100)
    if history is not None:
        history = [item for item in history if 0 <= source_time-item[0] <= 1.5]
    state = {name: getattr(geometry, name, None) for name in (
        'status', 'last_pose', 'last_digest', 'last_time', 'size', 'fit_center',
        'homography', 'pair_old_digest')}
    state.update(fits=fits, history_recent=history)
    return _plain(dict(source_receipt_sim_s=source_time, source_image_sha256=source_digest,
        enabled=bool(enabled), pixel_hits=pixel_hits,
        locate_called=bool(enabled and pixel_hits >= 2), box=box,
        geo_estimate=geo_estimate, geometry=state))
