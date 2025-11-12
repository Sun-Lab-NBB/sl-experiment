"""This package stores the data acquisition and preprocessing assets used by the Mesoscope-VR data acquisition system.
It exposes the APIs that allow interfacing with the Mesoscope-VR system to acquire new experiment data, train animals,
and preprocess already acquired data.
"""

from .zaber_bindings import CRCCalculator, discover_zaber_devices
from .data_acquisition import (
    experiment_logic,
    maintenance_logic,
    run_training_logic,
    lick_training_logic,
    window_checking_logic,
)
from .data_preprocessing import (
    purge_failed_session,
    purge_redundant_data,
    preprocess_session_data,
    migrate_animal_between_projects,
)

__all__ = [
    "CRCCalculator",
    "discover_zaber_devices",
    "experiment_logic",
    "lick_training_logic",
    "maintenance_logic",
    "migrate_animal_between_projects",
    "preprocess_session_data",
    "purge_failed_session",
    "purge_redundant_data",
    "run_training_logic",
    "window_checking_logic",
]
