"""Versioned public-planning JSONL datasets and episode-separated validation."""
import hashlib
import json
from pathlib import Path

import torch

from zqhj_features import FEATURE_VERSION, feature_vector
from learning.guidance import Scene


def load_records(paths):
    records,episodes,manifest = [],set(),[]
    for value in paths:
        path = Path(value).resolve()
        manifest.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        with path.open(encoding='utf-8') as stream:
            for line_number,line in enumerate(stream,1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get('feature_version') != FEATURE_VERSION:
                    raise ValueError(f'{path}:{line_number}: feature contract mismatch')
                if row.get('provenance') not in ('official_public_observation_train_mode','procedural_bootstrap'):
                    raise ValueError(f'{path}:{line_number}: unrecognized data provenance')
                episode = row.get('episode_id')
                if not isinstance(episode,str) or not episode:
                    raise ValueError('missing episode identifier')
                feature_vector(row['record'])
                records.append(row['record'])
                episodes.add(episode)
    if not records:
        raise ValueError('dataset contains no planning samples')
    return records,episodes,manifest


def scene_from_records(records,device='cpu'):
    kwargs = {name:torch.tensor([r[name] for r in records],dtype=torch.float32,device=device)
              for name in Scene.__dataclass_fields__}
    scene = Scene(**kwargs)
    scene.validate()
    return scene


def split_datasets(train_paths,val_paths):
    train,train_episodes,train_manifest = load_records(train_paths)
    valid,val_episodes,val_manifest = load_records(val_paths)
    if train_episodes & val_episodes:
        raise ValueError('train/validation share an episode; split by entire run, not frames or UAVs')
    if {m['sha256'] for m in train_manifest}&{m['sha256'] for m in val_manifest}:
        raise ValueError('train/validation contain duplicate files')
    return train,valid,dict(train=train_manifest,validation=val_manifest,
                           train_episodes=sorted(train_episodes),validation_episodes=sorted(val_episodes))
