# sl-shared-assets Modification Guide

Detailed guide for adding configuration support for a new acquisition system in sl-shared-assets. This guide covers
creating configuration dataclasses, registering the system, and exporting the new classes.

---

## Repository Location

The sl-shared-assets repository is located at `../sl-shared-assets/` relative to sl-experiment. All file paths in this
guide are relative to the sl-shared-assets repository root.

---

## Step 1: Create Configuration Module

Create a new file `src/sl_shared_assets/configuration/<system>_configuration.py` following the patterns in
`mesoscope_configuration.py`.

### Required Imports

```python
from dataclasses import dataclass, field
from pathlib import Path

from ataraxis_base_utilities import console
from ataraxis_data_structures import YamlConfig
```

### FileSystem Configuration (REQUIRED)

Every system MUST define a filesystem configuration with at minimum these paths:

```python
@dataclass
class [System]FileSystem:
    """Directory paths for [System] data storage.

    Attributes:
        root_directory: Root storage location on the acquisition PC. Used to construct session paths.
        server_directory: SMB mount point to the compute server for long-term storage.
        nas_directory: SMB mount point to NAS for archival backup storage.
    """

    root_directory: Path = Path()
    server_directory: Path = Path()
    nas_directory: Path = Path()
    # Add system-specific paths as needed (e.g., imaging_directory for a separate imaging PC)
```

### Hardware Configuration Dataclasses

Create dataclasses for each hardware category the system uses. Only include what the system actually needs.

**Camera Configuration Example:**

```python
@dataclass
class [System]Cameras:
    """Camera configuration for [System].

    Attributes:
        camera_index: Index of the camera in the Harvester camera interface list.
        camera_quantization: H.265 quantization parameter (0-51). Lower values produce higher quality.
        camera_preset: H.265 encoding speed preset (0-9). Higher values produce better compression.
    """

    camera_index: int = 0
    camera_quantization: int = 20
    camera_preset: int = 7
```

**Microcontroller Configuration Example:**

```python
@dataclass
class [System]MicroControllers:
    """Microcontroller configuration for [System].

    Attributes:
        controller_port: Serial port for the microcontroller (e.g., /dev/ttyACM0).
        keepalive_interval_ms: Interval between keepalive messages in milliseconds.
    """

    controller_port: str = "/dev/ttyACM0"
    keepalive_interval_ms: int = 500
    # Add sensor calibration parameters, thresholds, etc.
```

**External Assets Configuration Example:**

```python
@dataclass
class [System]ExternalAssets:
    """External hardware and network configuration for [System].

    Attributes:
        motor_port: Serial port for motor controller.
        mqtt_ip: IP address of MQTT broker for external communication.
        mqtt_port: Port number of MQTT broker.
    """

    motor_port: str = "/dev/ttyUSB0"
    mqtt_ip: str = "127.0.0.1"
    mqtt_port: int = 1883
```

### System Configuration Class (REQUIRED)

Combine all hardware configurations into the main system configuration:

```python
@dataclass
class [System]SystemConfiguration(YamlConfig):
    """Complete system configuration for [System] acquisition system.

    This class aggregates all hardware and filesystem configurations for the [System] system. It inherits from
    YamlConfig to enable YAML serialization and deserialization.

    Attributes:
        name: System identifier used for configuration file naming.
        filesystem: Directory paths for data storage.
        cameras: Camera indices and encoding parameters.
        microcontrollers: Serial ports and sensor calibration.
        assets: External hardware and network settings.
    """

    name: str = "<system_name>"
    filesystem: [System]FileSystem = field(default_factory=[System]FileSystem)
    cameras: [System]Cameras = field(default_factory=[System]Cameras)
    microcontrollers: [System]MicroControllers = field(default_factory=[System]MicroControllers)
    assets: [System]ExternalAssets = field(default_factory=[System]ExternalAssets)

    def __post_init__(self) -> None:
        """Validates configuration and restores Path objects from strings after YAML loading."""
        # Restore Path objects if loaded from YAML as strings
        if isinstance(self.filesystem.root_directory, str):
            self.filesystem.root_directory = Path(self.filesystem.root_directory)
        if isinstance(self.filesystem.server_directory, str):
            self.filesystem.server_directory = Path(self.filesystem.server_directory)
        if isinstance(self.filesystem.nas_directory, str):
            self.filesystem.nas_directory = Path(self.filesystem.nas_directory)

        # Add system-specific validation here
```

### Experiment Configuration Class (REQUIRED)

Every system MUST define an experiment configuration class. If using VR-based tasks, inherit structure from
`vr_configuration.py`. If using pure Python logic, define appropriate trial structures.

**VR-Based Example:**

```python
from .vr_configuration import Cue, Segment, VREnvironment
from .experiment_configuration import ExperimentState, WaterRewardTrial, GasPuffTrial

@dataclass
class [System]ExperimentConfiguration(YamlConfig):
    """Experiment configuration for [System] VR-based tasks.

    Attributes:
        cues: List of visual cues used in the VR environment.
        segments: List of corridor segments composed of cue sequences.
        trial_structures: Mapping of trial names to trial configuration objects.
        experiment_states: Mapping of state names to experiment state configurations.
        vr_environment: VR corridor environment parameters.
        unity_scene_name: Name of the Unity scene to load.
        cue_offset_cm: Offset for cue positioning in centimeters.
    """

    cues: list[Cue] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    trial_structures: dict[str, WaterRewardTrial | GasPuffTrial] = field(default_factory=dict)
    experiment_states: dict[str, ExperimentState] = field(default_factory=dict)
    vr_environment: VREnvironment = field(default_factory=VREnvironment)
    unity_scene_name: str = ""
    cue_offset_cm: float = 0.0

    def __post_init__(self) -> None:
        """Validates experiment configuration."""
        # Validate cue codes are unique
        codes = [cue.code for cue in self.cues]
        if len(codes) != len(set(codes)):
            console.error(message="Duplicate cue codes found", error=ValueError)

        # Add additional validation as needed
```

**Pure Python Logic Example:**

```python
from .experiment_configuration import ExperimentState, BaseTrial

@dataclass
class [System]ExperimentConfiguration(YamlConfig):
    """Experiment configuration for [System] Python-based tasks.

    Attributes:
        trial_structures: Mapping of trial names to trial configurations.
        experiment_states: Mapping of state names to experiment state configurations.
    """

    trial_structures: dict[str, BaseTrial] = field(default_factory=dict)
    experiment_states: dict[str, ExperimentState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validates experiment configuration."""
        # Add validation logic
```

---

## Step 2: Create Runtime Data Classes

Add system-specific descriptor classes to `src/sl_shared_assets/data_classes/runtime_data.py`.

### Session Descriptor Classes

Create descriptor classes for each session type the system supports:

```python
@dataclass(frozen=True)
class [System]ExperimentDescriptor:
    """Describes a [System] experiment session.

    Stores metadata about the experiment session including timing information and session parameters.

    Attributes:
        experiment_name: Name of the experiment configuration used.
        start_time: Session start time as numpy datetime64.
        end_time: Session end time as numpy datetime64.
    """

    experiment_name: str
    start_time: np.datetime64
    end_time: np.datetime64
    # Add session-specific fields
```

### Hardware State Classes

If the system tracks hardware state, create appropriate dataclasses:

```python
@dataclass(frozen=True)
class [System]HardwareState:
    """Records hardware state for [System] at session boundaries.

    Attributes:
        motor_positions: Dictionary mapping motor names to positions.
        sensor_baselines: Dictionary mapping sensor names to baseline values.
    """

    motor_positions: dict[str, float] = field(default_factory=dict)
    sensor_baselines: dict[str, int] = field(default_factory=dict)
```

---

## Step 3: Register System in configuration_utilities.py

Modify `src/sl_shared_assets/configuration/configuration_utilities.py` to register the new system.

### Add to AcquisitionSystems Enum

```python
class AcquisitionSystems(StrEnum):
    """Defines the data acquisition systems currently used in the Sun lab."""

    MESOSCOPE_VR = "mesoscope"
    [SYSTEM_NAME] = "<system_name>"  # Add new system
```

### Modify Type Aliases

Update the type aliases to include the new configuration classes:

```python
# Line ~36-40: Extend type aliases
SystemConfiguration = MesoscopeSystemConfiguration | [System]SystemConfiguration
ExperimentConfiguration = MesoscopeExperimentConfiguration | [System]ExperimentConfiguration
```

### Add to Config Class Registry

```python
# Line ~42-44: Add to _SYSTEM_CONFIG_CLASSES
_SYSTEM_CONFIG_CLASSES: dict[str, type[SystemConfiguration]] = {
    AcquisitionSystems.MESOSCOPE_VR: MesoscopeSystemConfiguration,
    AcquisitionSystems.[SYSTEM_NAME]: [System]SystemConfiguration,  # Add new system
}
```

### Create Factory Function

Add a factory function for creating experiment configurations:

```python
def _create_[system]_experiment_config(
    template: TaskTemplate,
    unity_scene_name: str,
    trial_structures: dict[str, WaterRewardTrial | GasPuffTrial],  # Adjust types as needed
    cue_offset_cm: float,
) -> [System]ExperimentConfiguration:
    """Creates a [System] experiment configuration from a task template.

    Args:
        template: The task template containing cues, segments, and VR environment settings.
        unity_scene_name: Name of the Unity scene to load.
        trial_structures: Mapping of trial names to configured trial objects.
        cue_offset_cm: Offset for cue positioning.

    Returns:
        Configured [System]ExperimentConfiguration instance.
    """
    return [System]ExperimentConfiguration(
        cues=template.cues,
        segments=template.segments,
        trial_structures=trial_structures,
        experiment_states={},  # Populated separately or passed in
        vr_environment=template.vr_environment,
        unity_scene_name=unity_scene_name,
        cue_offset_cm=cue_offset_cm,
    )
```

### Add to Factory Registry

```python
# Line ~52-55: Add to _EXPERIMENT_CONFIG_FACTORIES
_EXPERIMENT_CONFIG_FACTORIES: dict[str, ExperimentConfigFactory] = {
    AcquisitionSystems.MESOSCOPE_VR: _create_mesoscope_experiment_config,
    AcquisitionSystems.[SYSTEM_NAME]: _create_[system]_experiment_config,  # Add new system
}
```

### Add Required Imports

At the top of configuration_utilities.py, add imports for the new configuration classes:

```python
from .[system]_configuration import (
    [System]SystemConfiguration,
    [System]ExperimentConfiguration,
)
```

---

## Step 4: Update Exports

### configuration/__init__.py

Add exports for the new configuration classes:

```python
from .[system]_configuration import (
    [System]Cameras,
    [System]FileSystem,
    [System]ExternalAssets,
    [System]MicroControllers,
    [System]SystemConfiguration,
    [System]ExperimentConfiguration,
)
```

### data_classes/__init__.py

Add exports for new runtime data classes:

```python
from .runtime_data import (
    # ... existing exports ...
    [System]ExperimentDescriptor,
    [System]HardwareState,
)
```

### Top-level __init__.py

Add exports to the main package `__init__.py`:

```python
from .configuration import (
    # ... existing exports ...
    [System]Cameras,
    [System]FileSystem,
    [System]ExternalAssets,
    [System]MicroControllers,
    [System]SystemConfiguration,
    [System]ExperimentConfiguration,
)

from .data_classes import (
    # ... existing exports ...
    [System]ExperimentDescriptor,
    [System]HardwareState,
)
```

---

## Step 5: Update Version

Bump the version in `pyproject.toml`:

```toml
[project]
version = "X.Y.Z"  # Increment appropriately
```

Follow semantic versioning:
- MAJOR: Breaking API changes
- MINOR: New features (like adding a new system)
- PATCH: Bug fixes

---

## File Summary

| File                                       | Action | Changes                                 |
|--------------------------------------------|--------|-----------------------------------------|
| `configuration/<system>_configuration.py`  | CREATE | All system configuration dataclasses    |
| `configuration/configuration_utilities.py` | MODIFY | Enum, type aliases, registries, factory |
| `configuration/__init__.py`                | MODIFY | Export new configuration classes        |
| `data_classes/runtime_data.py`             | MODIFY | Add descriptor and state classes        |
| `data_classes/__init__.py`                 | MODIFY | Export new data classes                 |
| `__init__.py`                              | MODIFY | Export all new public classes           |
| `pyproject.toml`                           | MODIFY | Bump version                            |

---

## Validation

After making changes, verify:

1. **MyPy passes**: `mypy src/sl_shared_assets/`
2. **Imports work**: `python -c "from sl_shared_assets import [System]SystemConfiguration"`
3. **YAML round-trip**: Create a config instance, save to YAML, reload, verify equality
4. **Factory works**: Test `create_experiment_configuration()` with new system type
