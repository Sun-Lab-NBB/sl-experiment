# Camera Interface Guide for sl-experiment

This guide documents how to implement camera functionality in sl-experiment using the
ataraxis-video-system library. It covers both integration into existing acquisition systems and
creation of de-novo systems.

---

## IMPORTANT: Verification Requirement

**Before writing any camera code, you MUST verify the current state of the dependent libraries.**
The documentation in this guide may be outdated as the libraries evolve.

### Step 0: Version Verification

Follow the **Cross-Referenced Library Verification** procedure in `CLAUDE.md` to ensure local copies
of `ataraxis-video-system` and `sl-shared-assets` are up to date with their GitHub repositories.
If version mismatches exist, ask the user how to proceed before continuing.

### Content Verification

After confirming versions are acceptable, perform the following content checks:

### 1. Verify ataraxis-video-system

| File                                                                       | What to Check                                       |
|----------------------------------------------------------------------------|-----------------------------------------------------|
| `/home/cyberaxolotl/Desktop/GitHubRepos/ataraxis-video-system/README.md`   | Current usage instructions and quickstart examples  |
| `/home/cyberaxolotl/Desktop/GitHubRepos/ataraxis-video-system/examples/`   | Recommended usage patterns and integration examples |
| `src/ataraxis_video_system/__init__.py`                                    | Exported classes, functions, and public API surface |
| `src/ataraxis_video_system/video_system.py`                                | `VideoSystem` constructor parameters and methods    |
| `src/ataraxis_video_system/camera.py`                                      | `CameraInterfaces` enum and discovery functions     |
| `src/ataraxis_video_system/saver.py`                                       | Video encoder enums and pixel format options        |
| sl-experiment `pyproject.toml`                                             | Current pinned version dependency for this library  |

### 2. Verify sl-shared-assets

| File                                                                       | What to Check                                       |
|----------------------------------------------------------------------------|-----------------------------------------------------|
| `/home/cyberaxolotl/Desktop/GitHubRepos/sl-shared-assets/README.md`        | Current conventions and usage patterns              |
| `src/sl_shared_assets/__init__.py`                                         | Exported classes, functions, and public API surface |
| `src/sl_shared_assets/data_classes/configuration_data.py`                  | Camera dataclasses, enums, and field conventions    |
| `src/sl_shared_assets/data_classes/session_data.py`                        | `RawData` class and camera output path fields       |

### 3. Verify sl-experiment binding patterns

| File                                                                       | What to Check                                       |
|----------------------------------------------------------------------------|-----------------------------------------------------|
| `src/sl_experiment/mesoscope_vr/binding_classes.py`                        | Current `VideoSystems` wrapper implementation       |
| `src/sl_experiment/mesoscope_vr/data_acquisition.py`                       | Camera lifecycle integration and method call order  |

**If any discrepancies are found between this guide and the actual library state, follow the
current library implementation rather than this documentation.**

---

## Decision Logic

When implementing camera functionality, follow this decision tree:

```
Does the acquisition system already have a binding class in sl-experiment?
│
├─ YES → Integrate cameras into the existing binding class
│        (See: "Integrating into Existing Binding Classes")
│
└─ NO  → Create a new binding hierarchy for the acquisition system
         (See: "Creating De-Novo Acquisition Systems")
```

**Existing binding classes:**
- `src/sl_experiment/mesoscope_vr/binding_classes.py` - Mesoscope-VR system

---

## Integrating into Existing Binding Classes

If the target acquisition system already has a binding class, add camera support by:

1. **Adding a camera wrapper class** to the existing `binding_classes.py`
2. **Creating camera configuration** in sl-shared-assets (if not already present)
3. **Integrating with the data acquisition module** to manage camera lifecycle

### Example: Adding Cameras to an Existing System

```python
# In the existing binding_classes.py
from ataraxis_video_system import (
    VideoSystem,
    VideoEncoders,
    CameraInterfaces,
    OutputPixelFormats,
    EncoderSpeedPresets,
)

class NewCameraWrapper:
    """Manages video acquisition for the [SystemName] acquisition system."""

    def __init__(
        self,
        data_logger: DataLogger,
        output_directory: Path,
        camera_configuration: YourSystemCameras,  # From sl-shared-assets
    ) -> None:
        self._camera: VideoSystem = VideoSystem(
            system_id=np.uint8(XX),  # Unique ID for this camera
            data_logger=data_logger,
            output_directory=output_directory,
            camera_index=camera_configuration.camera_index,
            camera_interface=CameraInterfaces.HARVESTERS,
            # ... other parameters from configuration
        )
        self._camera_started: bool = False

    def start(self) -> None:
        """Starts frame acquisition."""
        if self._camera_started:
            return
        self._camera.start()
        self._camera_started = True

    def start_saving(self) -> None:
        """Enables frame saving to disk."""
        self._camera.start_frame_saving()

    def stop(self) -> None:
        """Stops acquisition and releases resources."""
        if self._camera_started:
            self._camera.stop_frame_saving()
        self._camera.stop()
        self._camera_started = False
```

---

## Creating De-Novo Acquisition Systems

For new acquisition systems without existing binding classes, create the full hierarchy following
the mesoscope_vr pattern.

### Required Components

#### 1. sl-shared-assets Configuration Classes

Before implementing in sl-experiment, the following must be added to sl-shared-assets:

**File:** `sl-shared-assets/src/sl_shared_assets/data_classes/configuration_data.py`

```python
# 1. Add enum member for the new system
class AcquisitionSystems(StrEnum):
    MESOSCOPE_VR = "mesoscope"
    YOUR_SYSTEM = "your_system"  # ADD THIS

# 2. Create camera configuration dataclass
@dataclass()
class YourSystemCameras:
    """Stores the video camera configuration for the YourSystem acquisition system."""

    primary_camera_index: int = 0
    """The index of the primary camera in the list of available cameras."""

    primary_camera_quantization: int = 20
    """The quantization parameter (0-51) for video encoding. Lower = higher quality."""

    primary_camera_preset: int = 7
    """The encoding speed preset. Must be a valid EncoderSpeedPresets member (0-5)."""

    # Add additional cameras as needed
    secondary_camera_index: int = 1
    """The index of the secondary camera."""

    secondary_camera_quantization: int = 20
    """The quantization parameter for the secondary camera."""

    secondary_camera_preset: int = 7
    """The encoding speed preset for the secondary camera."""

# 3. Create system configuration container
@dataclass()
class YourSystemConfiguration(YamlConfig):
    """Defines hardware and software configuration for the YourSystem acquisition system."""

    name: str = str(AcquisitionSystems.YOUR_SYSTEM)
    """The name identifier for this acquisition system."""

    filesystem: YourSystemFileSystem = field(default_factory=YourSystemFileSystem)
    """Filesystem path configuration for data storage."""

    cameras: YourSystemCameras = field(default_factory=YourSystemCameras)
    """Camera hardware configuration."""

    # Add other components as needed (microcontrollers, external assets, etc.)

    def __post_init__(self) -> None:
        """Validates and converts loaded configuration data."""
        # Convert Path strings back to Path objects after YAML loading
        self.filesystem.root_directory = Path(self.filesystem.root_directory)

    def save(self, path: Path) -> None:
        """Saves configuration to YAML file."""
        original = deepcopy(self)
        original.filesystem.root_directory = str(original.filesystem.root_directory)
        original.to_yaml(file_path=path)
```

**Required sl-shared-assets updates checklist:**
- [ ] Add `AcquisitionSystems` enum member
- [ ] Create `YourSystemCameras` dataclass with camera parameters
- [ ] Create `YourSystemFileSystem` dataclass with storage paths
- [ ] Create `YourSystemConfiguration` container class
- [ ] Update `get_system_configuration_data()` to recognize new config file
- [ ] Export new classes from `__init__.py`

#### 2. sl-experiment Binding Classes

**File:** `sl-experiment/src/sl_experiment/your_system/binding_classes.py`

```python
"""Provides hardware binding classes for the YourSystem acquisition system."""

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from ataraxis_data_structures import DataLogger
from ataraxis_video_system import (
    VideoSystem,
    VideoEncoders,
    CameraInterfaces,
    OutputPixelFormats,
    EncoderSpeedPresets,
)

if TYPE_CHECKING:
    from sl_shared_assets import YourSystemCameras


class VideoSystems:
    """Manages video acquisition from cameras in the YourSystem acquisition system.

    Args:
        data_logger: The DataLogger instance for timestamp logging.
        output_directory: The directory path for saving video files.
        camera_configuration: Camera settings from system configuration.

    Attributes:
        _primary_camera: VideoSystem instance for the primary camera.
        _primary_camera_started: Tracks whether primary camera acquisition has started.
        _secondary_camera: VideoSystem instance for the secondary camera.
        _secondary_camera_started: Tracks whether secondary camera acquisition has started.
    """

    def __init__(
        self,
        data_logger: DataLogger,
        output_directory: Path,
        camera_configuration: "YourSystemCameras",
    ) -> None:
        self._primary_camera: VideoSystem = VideoSystem(
            system_id=np.uint8(51),
            data_logger=data_logger,
            output_directory=output_directory,
            camera_index=camera_configuration.primary_camera_index,
            camera_interface=CameraInterfaces.HARVESTERS,
            display_frame_rate=25,
            video_encoder=VideoEncoders.H265,
            gpu=0,
            encoder_speed_preset=EncoderSpeedPresets(
                camera_configuration.primary_camera_preset
            ),
            output_pixel_format=OutputPixelFormats.YUV420,
            quantization_parameter=camera_configuration.primary_camera_quantization,
        )
        self._primary_camera_started: bool = False

        self._secondary_camera: VideoSystem = VideoSystem(
            system_id=np.uint8(62),
            data_logger=data_logger,
            output_directory=output_directory,
            camera_index=camera_configuration.secondary_camera_index,
            camera_interface=CameraInterfaces.HARVESTERS,
            display_frame_rate=25,
            video_encoder=VideoEncoders.H265,
            gpu=0,
            encoder_speed_preset=EncoderSpeedPresets(
                camera_configuration.secondary_camera_preset
            ),
            output_pixel_format=OutputPixelFormats.YUV420,
            quantization_parameter=camera_configuration.secondary_camera_quantization,
        )
        self._secondary_camera_started: bool = False

    def start_primary_camera(self) -> None:
        """Starts acquiring frames from the primary camera."""
        if self._primary_camera_started:
            return
        self._primary_camera.start()
        self._primary_camera_started = True

    def start_secondary_camera(self) -> None:
        """Starts acquiring frames from the secondary camera."""
        if self._secondary_camera_started:
            return
        self._secondary_camera.start()
        self._secondary_camera_started = True

    def save_primary_camera_frames(self) -> None:
        """Starts saving frames from the primary camera to disk."""
        self._primary_camera.start_frame_saving()

    def save_secondary_camera_frames(self) -> None:
        """Starts saving frames from the secondary camera to disk."""
        self._secondary_camera.start_frame_saving()

    def stop(self) -> None:
        """Stops acquiring and saving frames for all managed cameras."""
        if self._primary_camera_started:
            self._primary_camera.stop_frame_saving()
        self._primary_camera.stop()
        self._primary_camera_started = False

        if self._secondary_camera_started:
            self._secondary_camera.stop_frame_saving()
        self._secondary_camera.stop()
        self._secondary_camera_started = False
```

#### 3. Data Acquisition Integration

**File:** `sl-experiment/src/sl_experiment/your_system/data_acquisition.py`

```python
# Camera initialization (in __init__ or setup method)
self._cameras: VideoSystems = VideoSystems(
    data_logger=self._logger,
    output_directory=self._session_data.raw_data.camera_data_path,
    camera_configuration=self._system_configuration.cameras,
)

# Starting cameras (preview mode, no saving)
self._cameras.start_primary_camera()
self._cameras.start_secondary_camera()

# Begin recording (after user confirmation or checkpoint)
self._cameras.save_primary_camera_frames()
self._cameras.save_secondary_camera_frames()

# Shutdown (in cleanup method)
self._cameras.stop()
```

---

## sl-shared-assets Reference

### Camera Configuration Pattern

The `MesoscopeCameras` class demonstrates the standard camera configuration pattern:

**File:** `sl-shared-assets/src/sl_shared_assets/data_classes/configuration_data.py`

```python
@dataclass()
class MesoscopeCameras:
    """Stores the video camera configuration of the Mesoscope-VR data acquisition system."""

    face_camera_index: int = 0
    """The index of the face camera in the list of all available Harvester-managed cameras."""

    body_camera_index: int = 1
    """The index of the body camera in the list of all available Harvester-managed cameras."""

    face_camera_quantization: int = 20
    """The quantization parameter used by the face camera to encode acquired frames."""

    face_camera_preset: int = 7
    """The encoding speed preset used by the face camera."""

    body_camera_quantization: int = 20
    """The quantization parameter used by the body camera to encode acquired frames."""

    body_camera_preset: int = 7
    """The encoding speed preset used by the body camera."""
```

### Configuration Parameters

| Parameter               | Type  | Range | Description                                                        |
|-------------------------|-------|-------|--------------------------------------------------------------------|
| `*_camera_index`        | `int` | 0+    | Camera index returned by `get_harvesters_ids` or `get_opencv_ids`  |
| `*_camera_quantization` | `int` | 0-51  | Video encoding quality parameter (lower values = higher quality)   |
| `*_camera_preset`       | `int` | 0-5   | Encoding speed preset value (maps to `EncoderSpeedPresets` enum)   |

### System Configuration Container

Camera configuration is nested within the system configuration:

```python
@dataclass()
class MesoscopeSystemConfiguration(YamlConfig):
    name: str = str(AcquisitionSystems.MESOSCOPE_VR)
    filesystem: MesoscopeFileSystem = field(default_factory=MesoscopeFileSystem)
    cameras: MesoscopeCameras = field(default_factory=MesoscopeCameras)
    microcontrollers: MesoscopeMicroControllers = field(default_factory=...)
    # ...
```

### Session Data Paths

Camera output paths are defined in the session data hierarchy:

**File:** `sl-shared-assets/src/sl_shared_assets/data_classes/session_data.py`

```python
@dataclass()
class RawData:
    raw_data_path: Path           # Root for raw data
    camera_data_path: Path        # Video files stored here
    behavior_data_path: Path      # Non-video sensor data
    # ...
```

---

## ataraxis-video-system API Reference

### Core Import

```python
from ataraxis_video_system import (
    VideoSystem,
    VideoEncoders,
    CameraInterfaces,
    OutputPixelFormats,
    EncoderSpeedPresets,
    InputPixelFormats,
    get_opencv_ids,
    get_harvesters_ids,
    add_cti_file,
    check_ffmpeg_availability,
    check_gpu_availability,
)
```

### VideoSystem

The main orchestration class for camera acquisition and video encoding.

**Constructor Parameters:**

| Parameter                | Type                  | Required | Description                                            |
|--------------------------|-----------------------|----------|--------------------------------------------------------|
| `system_id`              | `np.uint8`            | Yes      | Unique identifier for DataLogger timestamp correlation |
| `data_logger`            | `DataLogger`          | Yes      | Shared logger instance for frame timestamp logging     |
| `output_directory`       | `Path \| None`        | No       | Directory for video output (None disables saving)      |
| `camera_interface`       | `CameraInterfaces`    | No       | Camera backend: HARVESTERS, OPENCV, or MOCK            |
| `camera_index`           | `int`                 | No       | Camera index from discovery functions (default 0)      |
| `frame_rate`             | `int \| None`         | No       | Override native camera frame rate in FPS               |
| `frame_width`            | `int \| None`         | No       | Override native camera frame width in pixels           |
| `frame_height`           | `int \| None`         | No       | Override native camera frame height in pixels          |
| `color`                  | `bool`                | No       | Color mode: True for BGR, False for MONOCHROME         |
| `display_frame_rate`     | `int \| None`         | No       | Live preview rate in FPS (None disables preview)       |
| `gpu`                    | `int`                 | No       | GPU index for hardware encoding (-1 for CPU only)      |
| `video_encoder`          | `VideoEncoders`       | No       | Video codec: H264 or H265 (H265 recommended)           |
| `encoder_speed_preset`   | `EncoderSpeedPresets` | No       | Encoding speed vs quality tradeoff (FASTEST-SLOWEST)   |
| `output_pixel_format`    | `OutputPixelFormats`  | No       | Output color format: YUV420 or YUV444                  |
| `quantization_parameter` | `int`                 | No       | Quality parameter 0-51 (lower = higher quality)        |

**Methods:**

| Method                 | Description                                                               |
|------------------------|---------------------------------------------------------------------------|
| `start()`              | Spawns producer (acquisition) and consumer (encoding) multiprocesses      |
| `stop()`               | Terminates all processes and releases camera and encoder resources        |
| `start_frame_saving()` | Enables writing encoded frames to disk (call after `start()`)            |
| `stop_frame_saving()`  | Stops writing frames to disk while keeping acquisition active             |

**Properties:**

| Property          | Type           | Description                                                    |
|-------------------|----------------|----------------------------------------------------------------|
| `video_file_path` | `Path \| None` | Full path to the output MP4 file (None if saving disabled)     |
| `started`         | `bool`         | True if producer and consumer processes are currently running  |
| `system_id`       | `np.uint8`     | The unique system identifier assigned at construction          |

### Enumerations

#### CameraInterfaces

```python
CameraInterfaces.HARVESTERS  # GeniCam-compatible cameras (GigE, USB3 Vision)
CameraInterfaces.OPENCV      # Consumer-grade USB cameras
CameraInterfaces.MOCK        # Testing only (simulated camera)
```

#### VideoEncoders

```python
VideoEncoders.H264  # Wider compatibility
VideoEncoders.H265  # Better compression (recommended)
```

#### EncoderSpeedPresets

```python
EncoderSpeedPresets.FASTEST   # Value: 0 - Lowest quality, highest speed
EncoderSpeedPresets.FAST      # Value: 1
EncoderSpeedPresets.MEDIUM    # Value: 2
EncoderSpeedPresets.SLOW      # Value: 3
EncoderSpeedPresets.SLOWER    # Value: 4
EncoderSpeedPresets.SLOWEST   # Value: 5 - Highest quality, lowest speed
```

#### OutputPixelFormats

```python
OutputPixelFormats.YUV420  # Standard, good for monochrome
OutputPixelFormats.YUV444  # Better color accuracy
```

### Discovery Functions

```python
# Discover OpenCV cameras
cameras = get_opencv_ids()
for cam in cameras:
    print(f"Index: {cam.camera_index}, {cam.frame_width}x{cam.frame_height}")

# Discover Harvesters (GeniCam) cameras
cameras = get_harvesters_ids()
for cam in cameras:
    print(f"Model: {cam.model}, Serial: {cam.serial_number}")

# Configure GenTL Producer (required once per system for Harvesters)
add_cti_file(cti_path=Path("/opt/mvIMPACT_Acquire/lib/x86_64/mvGenTLProducer.cti"))
```

### Utility Functions

```python
# Check external dependencies
if check_ffmpeg_availability():
    print("FFMPEG available")

if check_gpu_availability():
    print("GPU encoding available")
```

---

## System ID Allocation

Each camera requires a unique `system_id` for DataLogger differentiation:

| ID Range | Purpose                                                                     |
|----------|-----------------------------------------------------------------------------|
| 1-49     | Reserved for non-camera hardware systems (microcontrollers, sensors, etc.)  |
| 50-99    | Camera and video acquisition systems (use this range for new cameras)       |
| 100+     | Reserved for future system types and expansion                              |

**Current allocations (Mesoscope-VR):**
- `51` - Face camera
- `62` - Body camera

For new systems, select unused IDs within the 50-99 range.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                    sl-shared-assets                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Configuration Classes                                    │  │
│  │  - YourSystemCameras (camera indices, encoding params)   │  │
│  │  - YourSystemConfiguration (system container)            │  │
│  │  - YourSystemFileSystem (storage paths)                  │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────────────────────┬────────────────────────────────────┘
                            │ imports configuration
┌───────────────────────────▼────────────────────────────────────┐
│                    sl-experiment                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Binding Classes (binding_classes.py)                     │  │
│  │  - VideoSystems wrapper class                             │  │
│  │  - Lifecycle management (start, save, stop)              │  │
│  │  - Idempotency guards                                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Data Acquisition (data_acquisition.py)                   │  │
│  │  - Instantiates VideoSystems                              │  │
│  │  - Coordinates camera lifecycle with experiment           │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────────────────────┬────────────────────────────────────┘
                            │ uses
┌───────────────────────────▼────────────────────────────────────┐
│                 ataraxis-video-system                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  VideoSystem (Core Driver)                                │  │
│  │  - Multiprocessing orchestration                          │  │
│  │  - Producer process (frame acquisition)                   │  │
│  │  - Consumer process (H.265 encoding via FFMPEG)          │  │
│  │  - GPU acceleration                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Camera Backends                                          │  │
│  │  - HarvestersCamera (GenICam: GigE, USB3 Vision)         │  │
│  │  - OpenCVCamera (USB webcams)                             │  │
│  │  - MockCamera (testing)                                   │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│                    Physical Hardware                           │
│  - GigE/USB3 Vision cameras                                   │
│  - Network/USB interfaces                                      │
│  - NVIDIA GPU (hardware encoding)                              │
└────────────────────────────────────────────────────────────────┘
```

---

## Implementation Checklist

### For Existing Acquisition Systems

- [ ] Create camera wrapper class in existing `binding_classes.py`
- [ ] Add camera configuration to sl-shared-assets (if not present)
- [ ] Integrate with data acquisition module
- [ ] Allocate unique system IDs for each camera

### For De-Novo Acquisition Systems

**sl-shared-assets updates:**
- [ ] Add `AcquisitionSystems` enum member
- [ ] Create `{SystemName}Cameras` dataclass
- [ ] Create `{SystemName}FileSystem` dataclass
- [ ] Create `{SystemName}Configuration` container class
- [ ] Update `get_system_configuration_data()` function
- [ ] Export new classes from `__init__.py`

**sl-experiment implementation:**
- [ ] Create `src/sl_experiment/{system_name}/` directory
- [ ] Create `binding_classes.py` with `VideoSystems` wrapper
- [ ] Create `data_acquisition.py` with camera lifecycle integration
- [ ] Allocate unique system IDs (50-99 range)

---

## Dependencies

### External Requirements

| Dependency       | Version | Purpose                                                            |
|------------------|---------|-------------------------------------------------------------------|
| FFMPEG           | 8.0.1+  | Backend for H.264/H.265 video encoding and container multiplexing |
| MvImpactAcquire  | 2.9.2+  | Provides GenTL Producer (.cti) for Harvesters camera interface    |
| NVIDIA GPU       | -       | Required for hardware-accelerated encoding (NVENC)                 |

### Python Dependencies

```
ataraxis-video-system==2.2.0
```

---

## Troubleshooting

**Camera not detected:**
- Verify driver software is installed
- For Harvesters: ensure `.cti` file is configured via `add_cti_file()`
- Check physical connections and power

**Encoding failures:**
- Verify FFMPEG is installed: `check_ffmpeg_availability()`
- Verify GPU is available: `check_gpu_availability()`
- Check GPU memory and thermal status

**Frame drops:**
- Reduce `display_frame_rate` or set to `None`
- Use faster `encoder_speed_preset`
- Increase `quantization_parameter` (reduces quality but faster)

**Process crashes:**
- Check DataLogger is properly initialized
- Ensure output directory exists and is writable
- Verify sufficient disk space
