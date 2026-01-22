"""This package provides the assets for acquiring and preprocessing data via the Mesoscope-VR data acquisition
system.
"""

from .zaber_bindings import (
    CRCCalculator,
    ZaberDeviceSettings,
    ZaberValidationResult,
    discover_zaber_devices,
    get_zaber_devices_info,
    get_zaber_device_settings,
    set_zaber_device_setting,
    validate_zaber_device_configuration,
)
from .data_acquisition import (
    experiment_logic,
    maintenance_logic,
    run_training_logic,
    lick_training_logic,
    window_checking_logic,
)
from .data_preprocessing import (
    purge_session,
    preprocess_session_data,
    migrate_animal_between_projects,
)

__all__ = [
    "CRCCalculator",
    "ZaberDeviceSettings",
    "ZaberValidationResult",
    "discover_zaber_devices",
    "experiment_logic",
    "get_zaber_device_settings",
    "get_zaber_devices_info",
    "lick_training_logic",
    "maintenance_logic",
    "migrate_animal_between_projects",
    "preprocess_session_data",
    "purge_session",
    "run_training_logic",
    "set_zaber_device_setting",
    "validate_zaber_device_configuration",
    "window_checking_logic",
]
