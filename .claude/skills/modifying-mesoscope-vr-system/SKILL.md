---
name: modifying-mesoscope-vr-system
description: >-
  Guides modifications to the Mesoscope-VR acquisition system, including adding new hardware, updating configuration
  dataclasses, and integrating with binding classes. Use when extending the mesoscope-vr system with new components.
---

# Modifying the Mesoscope-VR System

Guides modifications to the Mesoscope-VR acquisition system in sl-experiment. This skill covers the system-specific
changes required to add new hardware components, update configuration, and integrate with the runtime.

---

## When to Use This Skill

Use this skill when:

- Adding new hardware (cameras, sensors, motors) to mesoscope-vr
- Modifying existing hardware configuration parameters
- Integrating new binding classes into data_acquisition.py
- Updating CLI commands for mesoscope-vr
- Understanding the mesoscope-vr architecture

For low-level hardware interface implementation (ataraxis-video-system API, camera discovery, testing), use the
`/camera-interface` skill instead.

For adding an entirely new acquisition system (not mesoscope-vr), use the `/adding-acquisition-system` skill.

---

## Verification Requirements

**Before modifying system code, verify the current state of dependent libraries.**

Follow the **Cross-Referenced Library Verification** procedure in `CLAUDE.md`:

1. Check local sl-shared-assets version against GitHub
2. If version mismatch exists, ask the user how to proceed
3. Use the verified source for configuration patterns

### Files to Verify

| Repository       | File                                                | What to Check                         |
|------------------|-----------------------------------------------------|---------------------------------------|
| sl-shared-assets | `configuration/mesoscope_configuration.py`          | Current dataclass structure           |
| sl-shared-assets | `configuration/configuration_utilities.py`          | Registry patterns                     |
| sl-experiment    | `mesoscope_vr/binding_classes.py`                   | Binding class patterns                |
| sl-experiment    | `mesoscope_vr/data_acquisition.py`                  | Lifecycle integration                 |

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           sl-shared-assets                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  mesoscope_configuration.py                                          │  │
│  │  ───────────────────────────                                         │  │
│  │  MesoscopeFileSystem       - Storage paths                           │  │
│  │  MesoscopeCameras          - Camera indices, encoding params         │  │
│  │  MesoscopeMicroControllers - Port assignments, thresholds            │  │
│  │  MesoscopeExternalAssets   - Zaber motor ports, Google Sheets        │  │
│  │  MesoscopeSystemConfiguration - Container with all components        │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬──────────────────────────────────────────┘
                                  │ imports configuration
┌─────────────────────────────────▼──────────────────────────────────────────┐
│                              sl-experiment                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  binding_classes.py                                                  │  │
│  │  ──────────────────                                                  │  │
│  │  ZaberMotors              - Motor position management                │  │
│  │  MicroControllerInterfaces - AMC communication                       │  │
│  │  VideoSystems             - Camera frame acquisition                 │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  data_acquisition.py                                                 │  │
│  │  ───────────────────                                                 │  │
│  │  - Instantiates binding classes                                      │  │
│  │  - Coordinates hardware lifecycle                                    │  │
│  │  - Manages session state                                             │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Modification Workflow

Adding new hardware to mesoscope-vr requires changes in both repositories:

```
Phase 1: sl-shared-assets (Configuration)
├── 1.1 Add/modify configuration dataclass
├── 1.2 Update MesoscopeSystemConfiguration
├── 1.3 Export new classes
└── 1.4 Bump version

Phase 2: sl-experiment (Implementation)
├── 2.1 Add binding class to binding_classes.py
├── 2.2 Integrate into data_acquisition.py
├── 2.3 Update CLI commands (if needed)
└── 2.4 Update pyproject.toml dependency
```

---

## Phase 1: Configuration (sl-shared-assets)

### Step 1.1: Add Configuration Dataclass

**File:** `sl-shared-assets/src/sl_shared_assets/configuration/mesoscope_configuration.py`

Add a new dataclass or modify an existing one for the hardware component.

### Adding Camera Configuration Fields

To add a new camera to the system, modify `MesoscopeCameras`:

```python
@dataclass()
class MesoscopeCameras:
    """Stores the video camera configuration of the Mesoscope-VR data acquisition system."""

    # Existing cameras
    face_camera_index: int = 0
    """The index of the face camera in the list of all available Harvester-managed cameras."""

    face_camera_quantization: int = 20
    """The quantization parameter used by the face camera to encode acquired frames."""

    face_camera_preset: int = 7
    """The encoding speed preset used by the face camera."""

    body_camera_index: int = 1
    """The index of the body camera in the list of all available Harvester-managed cameras."""

    body_camera_quantization: int = 20
    """The quantization parameter used by the body camera to encode acquired frames."""

    body_camera_preset: int = 7
    """The encoding speed preset used by the body camera."""

    # ADD NEW CAMERA HERE
    new_camera_index: int = 2
    """The index of the new camera in the list of all available Harvester-managed cameras."""

    new_camera_quantization: int = 20
    """The quantization parameter used by the new camera to encode acquired frames."""

    new_camera_preset: int = 7
    """The encoding speed preset used by the new camera."""
```

### Adding New Hardware Category

For entirely new hardware types, create a new dataclass:

```python
@dataclass()
class MesoscopeNewHardware:
    """Configuration for new hardware component in the Mesoscope-VR system.

    Attributes:
        port: Serial port path for device communication.
        parameter_a: Description of parameter A.
        parameter_b: Description of parameter B.
    """

    port: str = "/dev/ttyUSB0"
    """Serial port path for the new hardware device."""

    parameter_a: int = 100
    """Description of what parameter A controls."""

    parameter_b: float = 1.5
    """Description of what parameter B controls."""
```

### Step 1.2: Update System Configuration

Add the new configuration to `MesoscopeSystemConfiguration`:

```python
@dataclass()
class MesoscopeSystemConfiguration(YamlConfig):
    """Defines hardware and software configuration for the Mesoscope-VR acquisition system."""

    name: str = str(AcquisitionSystems.MESOSCOPE_VR)
    filesystem: MesoscopeFileSystem = field(default_factory=MesoscopeFileSystem)
    cameras: MesoscopeCameras = field(default_factory=MesoscopeCameras)
    microcontrollers: MesoscopeMicroControllers = field(default_factory=MesoscopeMicroControllers)
    external_assets: MesoscopeExternalAssets = field(default_factory=MesoscopeExternalAssets)

    # ADD NEW HARDWARE CATEGORY HERE (if creating new dataclass)
    new_hardware: MesoscopeNewHardware = field(default_factory=MesoscopeNewHardware)
```

### Step 1.3: Export New Classes

**File:** `sl-shared-assets/src/sl_shared_assets/configuration/__init__.py`

Add the new class to exports:

```python
from .mesoscope_configuration import (
    MesoscopeFileSystem,
    MesoscopeCameras,
    MesoscopeMicroControllers,
    MesoscopeExternalAssets,
    MesoscopeSystemConfiguration,
    MesoscopeNewHardware,  # ADD THIS
)
```

**File:** `sl-shared-assets/src/sl_shared_assets/__init__.py`

Add to top-level exports:

```python
from .configuration import (
    # ... existing exports ...
    MesoscopeNewHardware,  # ADD THIS
)
```

### Step 1.4: Bump Version

Update `pyproject.toml` version number to reflect the configuration change.

---

## Phase 2: Implementation (sl-experiment)

### Step 2.1: Add Binding Class

**File:** `sl-experiment/src/sl_experiment/mesoscope_vr/binding_classes.py`

#### Adding to Existing VideoSystems Class

For new cameras, extend the `VideoSystems` class:

```python
class VideoSystems:
    """Interfaces with the Ataraxis Video System devices used in Mesoscope-VR."""

    def __init__(
        self,
        data_logger: DataLogger,
        camera_configuration: MesoscopeCameras,
        output_directory: Path,
    ) -> None:
        # Existing cameras...
        self._face_camera_started: bool = False
        self._body_camera_started: bool = False

        # ADD NEW CAMERA
        self._new_camera_started: bool = False
        self._new_camera: VideoSystem = VideoSystem(
            system_id=np.uint8(73),  # Allocate new ID in 50-99 range
            data_logger=data_logger,
            output_directory=output_directory,
            camera_index=camera_configuration.new_camera_index,
            camera_interface=CameraInterfaces.HARVESTERS,
            display_frame_rate=25,
            video_encoder=VideoEncoders.H265,
            gpu=0,
            encoder_speed_preset=EncoderSpeedPresets(camera_configuration.new_camera_preset),
            output_pixel_format=OutputPixelFormats.YUV420,
            quantization_parameter=camera_configuration.new_camera_quantization,
        )

    # Add lifecycle methods for new camera
    def start_new_camera(self) -> None:
        """Starts acquiring frames from the new camera."""
        if self._new_camera_started:
            return
        self._new_camera.start()
        self._new_camera_started = True

    def save_new_camera_frames(self) -> None:
        """Starts saving frames from the new camera to disk."""
        self._new_camera.start_frame_saving()

    def stop(self) -> None:
        """Stops all cameras."""
        # ... existing camera stop logic ...

        # ADD NEW CAMERA STOP
        if self._new_camera_started:
            self._new_camera.stop_frame_saving()
        self._new_camera.stop()
        self._new_camera_started = False
```

#### Creating New Binding Class

For new hardware categories, create a new class:

```python
class NewHardwareInterface:
    """Interfaces with new hardware in the Mesoscope-VR system.

    Args:
        data_logger: DataLogger instance for event logging.
        hardware_configuration: Configuration parameters from system config.

    Attributes:
        _started: Tracks whether the hardware is active.
        _config: Cached configuration parameters.
    """

    def __init__(
        self,
        data_logger: DataLogger,
        hardware_configuration: MesoscopeNewHardware,
    ) -> None:
        self._started: bool = False
        self._config: MesoscopeNewHardware = hardware_configuration
        # Initialize hardware connection
        # self._device = DeviceDriver(port=self._config.port)

    def __del__(self) -> None:
        """Ensures cleanup on garbage collection."""
        self.stop()

    def start(self) -> None:
        """Starts hardware operation."""
        if self._started:
            return
        # self._device.connect()
        # self._device.configure(self._config.parameter_a, self._config.parameter_b)
        self._started = True

    def stop(self) -> None:
        """Stops hardware and releases resources."""
        if not self._started:
            return
        # self._device.disconnect()
        self._started = False
```

### Step 2.2: Integrate into Data Acquisition

**File:** `sl-experiment/src/sl_experiment/mesoscope_vr/data_acquisition.py`

Add the new binding class to the session runtime.

#### Import New Binding Class

```python
from .binding_classes import (
    ZaberMotors,
    MicroControllerInterfaces,
    VideoSystems,
    NewHardwareInterface,  # ADD THIS
)
```

#### Instantiate in Session Setup

```python
# In the session setup function or class __init__
self._new_hardware: NewHardwareInterface = NewHardwareInterface(
    data_logger=self._logger,
    hardware_configuration=self._system_configuration.new_hardware,
)
```

#### Integrate Lifecycle

```python
# Start hardware
self._new_hardware.start()

# ... session runtime ...

# Stop hardware (in cleanup/finally block)
self._new_hardware.stop()
```

### Step 2.3: Update CLI (If Needed)

**File:** `sl-experiment/src/sl_experiment/command_line_interfaces/`

If the new hardware requires user-facing commands, add to the appropriate CLI module.

### Step 2.4: Update Dependencies

**File:** `sl-experiment/pyproject.toml`

Update the sl-shared-assets dependency version:

```toml
dependencies = [
    "sl-shared-assets>=X.Y.Z",  # Match version with new configuration
]
```

---

## Existing Configuration Reference

### MesoscopeCameras

| Field                       | Type  | Default | Description                            |
|-----------------------------|-------|---------|----------------------------------------|
| `face_camera_index`         | `int` | `0`     | Face camera index from discovery       |
| `face_camera_quantization`  | `int` | `20`    | Face camera encoding quality (0-51)    |
| `face_camera_preset`        | `int` | `7`     | Face camera encoding speed preset      |
| `body_camera_index`         | `int` | `1`     | Body camera index from discovery       |
| `body_camera_quantization`  | `int` | `20`    | Body camera encoding quality (0-51)    |
| `body_camera_preset`        | `int` | `7`     | Body camera encoding speed preset      |

### MesoscopeMicroControllers

| Field                                  | Type    | Description                               |
|----------------------------------------|---------|-------------------------------------------|
| `actor_port`                           | `str`   | Actor AMC serial port                     |
| `sensor_port`                          | `str`   | Sensor AMC serial port                    |
| `encoder_port`                         | `str`   | Encoder AMC serial port                   |
| `lick_threshold_adc`                   | `int`   | Lick detection threshold (ADC units)      |
| `valve_calibration_data`               | `tuple` | Water valve calibration curve points      |
| `minimum_brake_strength_g_cm`          | `int`   | Minimum brake torque (g*cm)               |
| `maximum_brake_strength_g_cm`          | `int`   | Maximum brake torque (g*cm)               |
| `wheel_encoder_ppr`                    | `int`   | Wheel encoder pulses per revolution       |
| `wheel_diameter_cm`                    | `float` | Running wheel diameter (cm)               |

### MesoscopeExternalAssets

| Field            | Type  | Description                           |
|------------------|-------|---------------------------------------|
| `headbar_port`   | `str` | Headbar Zaber motor group serial port |
| `wheel_port`     | `str` | Wheel Zaber motor serial port         |
| `lickport_port`  | `str` | Lickport Zaber motor group serial port|
| `spreadsheet_id` | `str` | Google Sheets document ID             |
| `sheet_name`     | `str` | Target worksheet name                 |

---

## System ID Allocation

Current mesoscope-vr allocations:

| ID    | Component              | Purpose                    |
|-------|------------------------|----------------------------|
| 51    | Face camera            | Frame timestamp logging    |
| 62    | Body camera            | Frame timestamp logging    |
| 101   | Actor AMC              | Microcontroller events     |
| 152   | Sensor AMC             | Microcontroller events     |
| 203   | Encoder AMC            | Microcontroller events     |

**Available ID ranges:**
- 50-99: Cameras (next available: 73)
- 100-199: Microcontrollers
- 200-255: Other hardware

---

## Verification Checklist

### Phase 1 (sl-shared-assets)

```
- [ ] Added/modified configuration dataclass with all required fields
- [ ] Each field has docstring explaining its purpose
- [ ] Updated MesoscopeSystemConfiguration (if new category)
- [ ] Exported new classes from configuration/__init__.py
- [ ] Exported from top-level __init__.py
- [ ] Bumped version in pyproject.toml
- [ ] MyPy strict passes
```

### Phase 2 (sl-experiment)

```
- [ ] Added binding class with lifecycle methods (start, stop)
- [ ] Binding class has __del__ for cleanup
- [ ] Binding class has idempotency guards
- [ ] Integrated into data_acquisition.py
- [ ] Updated CLI commands (if needed)
- [ ] Updated pyproject.toml dependency version
- [ ] Allocated unique system ID
- [ ] MyPy strict passes
```
