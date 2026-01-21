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

For low-level camera hardware implementation (ataraxis-video-system API, camera discovery, testing), use the
`/camera-interface` skill instead.

For low-level microcontroller hardware implementation (firmware modules, PC interfaces), use the
`/microcontroller-interface` skill instead.

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

---

## Adding Microcontroller Hardware Modules

For hardware controlled by Teensy microcontrollers (sensors, actuators, digital I/O), use the `/microcontroller-interface`
skill for the low-level firmware and PC interface implementation. This section covers the mesoscope-vr specific
integration steps.

### Hardware Type Decision Tree

```
New hardware component
├── Camera (video acquisition)
│   └── Use /camera-interface skill → Integrate via VideoSystems class
│
├── Microcontroller-based (sensors, actuators)
│   └── Use /microcontroller-interface skill → Integrate via MicroControllerInterfaces class
│
└── External device (motors, network services)
    └── Create custom binding class → Integrate directly in data_acquisition.py
```

### Microcontroller Module Integration Workflow

After implementing the firmware module and PC interface using `/microcontroller-interface`:

```
Phase 1: Configuration (sl-shared-assets)
├── 1.1 Add configuration fields to MesoscopeMicroControllers
└── 1.2 Export and bump version

Phase 2: Integration (sl-experiment)
├── 2.1 Import new ModuleInterface in module_interfaces.py (if not already there)
├── 2.2 Add interface to MicroControllerInterfaces binding class
├── 2.3 Add to appropriate controller's module_interfaces tuple
├── 2.4 Call initialize_local_assets() in binding class start()
├── 2.5 Configure parameters in binding class start()
└── 2.6 Use interface in data_acquisition.py runtime
```

### Step 1.1: Add Configuration to MesoscopeMicroControllers

**File:** `sl-shared-assets/src/sl_shared_assets/configuration/mesoscope_configuration.py`

```python
@dataclass()
class MesoscopeMicroControllers:
    """Configuration for microcontroller-managed hardware."""

    # Existing fields...
    actor_port: str = "/dev/ttyACM0"
    sensor_port: str = "/dev/ttyACM1"
    encoder_port: str = "/dev/ttyACM2"

    # ADD NEW MODULE CONFIGURATION
    new_module_parameter_a: int = 1000
    """Description of parameter A for the new module."""

    new_module_parameter_b: float = 2.5
    """Description of parameter B for the new module."""
```

### Step 2.2: Add Interface to MicroControllerInterfaces

**File:** `sl-experiment/src/sl_experiment/mesoscope_vr/binding_classes.py`

```python
from sl_experiment.shared_components import (
    # Existing imports...
    BrakeInterface,
    ValveInterface,
    NewModuleInterface,  # ADD IMPORT
)

class MicroControllerInterfaces:
    """Manages microcontroller communication for Mesoscope-VR."""

    def __init__(
        self,
        data_logger: DataLogger,
        config: MesoscopeMicroControllers,
    ) -> None:
        # Existing interfaces...
        self.brake = BrakeInterface(...)
        self.valve = ValveInterface(...)

        # ADD NEW INTERFACE
        self.new_module = NewModuleInterface(
            parameter_a=config.new_module_parameter_a,
            parameter_b=config.new_module_parameter_b,
        )

        # Add to appropriate controller's module_interfaces tuple
        self._actor: MicroControllerInterface = MicroControllerInterface(
            controller_id=np.uint8(101),
            data_logger=data_logger,
            module_interfaces=(
                self.brake,
                self.valve,
                self.gas_puff_valve,
                self.screens,
                self.new_module,  # ADD TO TUPLE
            ),
            buffer_size=8192,
            port=config.actor_port,
            baudrate=115200,
        )

    def start(self) -> None:
        """Starts all microcontroller communication."""
        self._actor.start()
        self._sensor.start()
        self._encoder.start()

        # Initialize local assets for interfaces that need them
        self.wheel_encoder.initialize_local_assets()
        self.valve.initialize_local_assets()
        self.new_module.initialize_local_assets()  # ADD THIS

        # Configure module parameters
        self.new_module.set_parameters(
            parameter_a=np.uint32(...),
            parameter_b=np.float32(...),
        )
```

### Controller Assignment

Assign modules to the appropriate microcontroller:

| Controller | ID  | Use For                                     | Modules Tuple Location            |
|------------|-----|---------------------------------------------|-----------------------------------|
| ACTOR      | 101 | Output control (valves, brakes, LEDs)       | `self._actor` module_interfaces   |
| SENSOR     | 152 | Input monitoring (lick, torque, TTL)        | `self._sensor` module_interfaces  |
| ENCODER    | 203 | High-speed timing (quadrature encoders)     | `self._encoder` module_interfaces |

### Step 2.6: Use in data_acquisition.py

```python
# Enable monitoring (for sensor modules)
self._microcontrollers.new_module.start_monitoring()

# Trigger commands
self._microcontrollers.new_module.execute_action()

# Read state
if self._microcontrollers.new_module.is_active:
    value = self._microcontrollers.new_module.current_value

# Disable monitoring
self._microcontrollers.new_module.stop_monitoring()
```

### Existing Module Type Codes

Current allocations in mesoscope-vr (must not reuse):

| Type Code | Module           | Controller |
|-----------|------------------|------------|
| 1         | TTLModule        | SENSOR     |
| 2         | EncoderModule    | ENCODER    |
| 3         | BrakeModule      | ACTOR      |
| 4         | LickModule       | SENSOR     |
| 5         | ValveModule      | ACTOR      |
| 6         | TorqueModule     | SENSOR     |
| 7         | ScreenModule     | ACTOR      |

**Next available type code:** 8

### Microcontroller Module Checklist

```
- [ ] Firmware module implemented (see /microcontroller-interface skill)
- [ ] PC interface implemented (see /microcontroller-interface skill)
- [ ] Configuration fields added to MesoscopeMicroControllers
- [ ] Interface instantiated in MicroControllerInterfaces.__init__
- [ ] Interface added to correct controller's module_interfaces tuple
- [ ] initialize_local_assets() called in MicroControllerInterfaces.start()
- [ ] Parameters configured in MicroControllerInterfaces.start()
- [ ] Interface used in data_acquisition.py runtime
- [ ] MyPy strict passes
```
