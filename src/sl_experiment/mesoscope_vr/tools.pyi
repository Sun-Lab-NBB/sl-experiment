from enum import IntEnum
from pathlib import Path
from dataclasses import field, dataclass

import numpy as np
from _typeshed import Incomplete
from numpy.typing import NDArray as NDArray
from sl_shared_assets import (
    SessionData as SessionData,
    MesoscopeSystemConfiguration,
)

def get_system_configuration() -> MesoscopeSystemConfiguration: ...

mesoscope_vr_sessions: tuple[str, str, str, str]

class _DataArrayIndex(IntEnum):
    TERMINATION = 0
    EXIT_SIGNAL = 1
    REWARD_SIGNAL = 2
    SPEED_MODIFIER = 3
    DURATION_MODIFIER = 4
    PAUSE_STATE = 5
    OPEN_VALVE = 6
    CLOSE_VALVE = 7
    REWARD_VOLUME = 8
    GUIDANCE_ENABLED = 9

@dataclass()
class _VRPCPersistentData:
    session_type: str
    persistent_data_path: Path
    zaber_positions_path: Path = field(default_factory=Path, init=False)
    mesoscope_positions_path: Path = field(default_factory=Path, init=False)
    session_descriptor_path: Path = field(default_factory=Path, init=False)
    window_screenshot_path: Path = field(default_factory=Path, init=False)
    def __post_init__(self) -> None: ...

@dataclass()
class _ScanImagePCData:
    session: str
    meso_data_path: Path
    persistent_data_path: Path
    mesoscope_data_path: Path = field(default_factory=Path, init=False)
    session_specific_path: Path = field(default_factory=Path, init=False)
    motion_estimator_path: Path = field(default_factory=Path, init=False)
    roi_path: Path = field(default_factory=Path, init=False)
    kinase_path: Path = field(default_factory=Path, init=False)
    phosphatase_path: Path = field(default_factory=Path, init=False)
    def __post_init__(self) -> None: ...

@dataclass()
class _VRPCDestinations:
    nas_data_path: Path
    server_data_path: Path

class MesoscopeData:
    vrpc_data: Incomplete
    scanimagepc_data: Incomplete
    destinations: Incomplete
    def __init__(self, system_configuration: MesoscopeSystemConfiguration, session_data: SessionData) -> None: ...

class CachedMotifDecomposer:
    _cached_motifs: list[NDArray[np.uint8]] | None
    _cached_flat_data: tuple[NDArray[np.uint8], NDArray[np.int32], NDArray[np.int32], NDArray[np.int32]] | None
    _cached_distances: NDArray[np.float32] | None
    def __init__(self) -> None: ...
    def prepare_motif_data(
        self, trial_motifs: list[NDArray[np.uint8]], trial_distances: list[float]
    ) -> tuple[NDArray[np.uint8], NDArray[np.int32], NDArray[np.int32], NDArray[np.int32], NDArray[np.float32]]: ...
