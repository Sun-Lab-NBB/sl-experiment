"""This package provides the assets for acquiring and preprocessing data via the Mesoscope-VR data acquisition system.
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
