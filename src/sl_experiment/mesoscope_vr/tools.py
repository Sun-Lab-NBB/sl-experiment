"""This module provides utility assets shared by other modules of the mesoscope_vr package."""

import sys
from enum import IntEnum
from pathlib import Path
import contextlib
from dataclasses import field, dataclass
from multiprocessing import Process

import numpy as np
from PyQt6.QtGui import QFont, QCloseEvent
from PyQt6.QtCore import Qt, QTimer
from numpy.typing import NDArray
from PyQt6.QtWidgets import (
    QLabel,
    QWidget,
    QGroupBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QApplication,
    QDoubleSpinBox,
)
from sl_shared_assets import SessionData, SessionTypes, MesoscopeSystemConfiguration, get_system_configuration_data
from ataraxis_base_utilities import console, ensure_directory_exists
from ataraxis_data_structures import SharedMemoryArray


def get_system_configuration() -> MesoscopeSystemConfiguration:
    """Verifies that the host-machine belongs to the Mesoscope-VR data acquisition system and loads the
    system configuration data as a MesoscopeSystemConfiguration instance.

    Returns:
        The data acquisition system configuration data as a MesoscopeSystemConfiguration instance.

    Raises:
        TypeError: If the host-machine does not belong to the Mesoscope-VR data acquisition system.
    """
    system_configuration = get_system_configuration_data()
    if not isinstance(system_configuration, MesoscopeSystemConfiguration):
        message = (
            f"Unable to resolve the configuration for the Mesoscope-VR data acquisition system, as the host-machine "
            f"belongs to the {system_configuration.name} data acquisition system. Use the 'sl-configure system' CLI "
            f"command to reconfigure the host-machine to belong the Mesoscope-VR data acquisition system."
        )
        console.error(message, error=TypeError)

        # Fallback to appease mypy, should not be reachable
        raise TypeError(message)  # pragma: no cover
    return system_configuration


mesoscope_vr_sessions: tuple[str, str, str, str] = (
    SessionTypes.LICK_TRAINING,
    SessionTypes.RUN_TRAINING,
    SessionTypes.MESOSCOPE_EXPERIMENT,
    SessionTypes.WINDOW_CHECKING,
)
"""Defines the data acquisition session types supported by the Mesoscope-VR data acquisition system."""


class _DataArrayIndex(IntEnum):
    """Defines the shared memory array indices for each runtime parameter addressable from the user-facing GUI."""

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
    SHOW_REWARD = 10


@dataclass()
class _VRPCPersistentData:
    """Defines the layout of the VRPC's 'persistent_data' directory, used to cache animal-specific runtime parameters
    between data acquisition sessions.
    """

    session_type: str
    """The type of the data acquisition session for which this instance was initialized."""
    persistent_data_path: Path
    """The path to the project- and animal-specific directory that stores the VRPC runtime parameters and data cached 
    between data acquisition runtimes."""
    zaber_positions_path: Path = field(default_factory=Path, init=False)
    """The path to the .YAML file that stores Zaber motor positions used during the previous session's runtime."""
    mesoscope_positions_path: Path = field(default_factory=Path, init=False)
    """The path to the .YAML file that stores the Mesoscope's imaging axis coordinates used during the previous 
    session's runtime."""
    session_descriptor_path: Path = field(default_factory=Path, init=False)
    """The path to the .YAML file that stores the data acquisition session's task parameters used during the previous 
    session's runtime."""
    window_screenshot_path: Path = field(default_factory=Path, init=False)
    """The path to the .PNG file that stores the screenshot of the imaging window, the red-dot alignment state, and the 
    Mesoscope's data-acquisition configuration used during the previous session's runtime."""

    def __post_init__(self) -> None:
        """Resolves the managed directory layout, creating any missing directory components."""
        # Resolves paths that can be derived from the root path.
        self.zaber_positions_path = self.persistent_data_path.joinpath("zaber_positions.yaml")
        self.mesoscope_positions_path = self.persistent_data_path.joinpath("mesoscope_positions.yaml")
        self.window_screenshot_path = self.persistent_data_path.joinpath("window_screenshot.png")

        # Resolves the session descriptor path based on the session type.
        if self.session_type == SessionTypes.LICK_TRAINING:
            self.session_descriptor_path = self.persistent_data_path.joinpath("lick_training_descriptor.yaml")
        elif self.session_type == SessionTypes.RUN_TRAINING:
            self.session_descriptor_path = self.persistent_data_path.joinpath("run_training_descriptor.yaml")
        elif self.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
            self.session_descriptor_path = self.persistent_data_path.joinpath("mesoscope_experiment_descriptor.yaml")
        elif self.session_type == SessionTypes.WINDOW_CHECKING:
            self.session_descriptor_path = self.persistent_data_path.joinpath("window_checking_descriptor.yaml")

        else:  # Raises an error for unsupported session types
            message = (
                f"Unsupported session type '{self.session_type}' encountered when resolving the filesystem layout for "
                f"the Mesoscope-VR data acquisition system. Currently, only the following data acquisition session "
                f"types are supported: {','.join(mesoscope_vr_sessions)}."
            )
            console.error(message, error=ValueError)

        # Ensures that the target persistent_data directory exists
        ensure_directory_exists(self.persistent_data_path)


@dataclass()
class _ScanImagePCData:
    """Defines the layout of the ScanImagePC's 'meso_data' directory used to aggregate all Mesoscope-acquired data
    during a data acquisition session's runtime.
    """

    session: str
    """The unique identifier of the session for which this instance was initialized."""
    meso_data_path: Path
    """The path to the root ScanImagePC data-output directory."""
    persistent_data_path: Path
    """The path to the project- and animal-specific directory that stores the ScanImagePC (Mesoscope) runtime parameters
    and data cached between data acquisition runtimes."""
    mesoscope_data_path: Path = field(default_factory=Path, init=False)
    """The path to the directory used by the Mesoscope to save all acquired data during the acquisition session's 
    runtime, which is shared by all data acquisition sessions."""
    session_specific_path: Path = field(default_factory=Path, init=False)
    """The path to the session-specific directory where all Mesoscope-acquired data is moved at the end of each data 
    acquisition session's runtime."""
    motion_estimator_path: Path = field(default_factory=Path, init=False)
    """The path top the animal-specific reference .ME (motion estimator) file, used to align the Mesoscope's imaging 
    field to the same view across all data acquisition sessions."""
    roi_path: Path = field(default_factory=Path, init=False)
    """The path top the animal-specific reference .ROI (Region-of-Interest) file, used to restore the same imaging 
    field across all data acquisition sessions."""
    kinase_path: Path = field(default_factory=Path, init=False)
    """The path to the 'kinase.bin' file used to lock the MATLAB's runtime function (setupAcquisition.m) into the data 
    acquisition mode until the kinase marker is removed by the VRPC."""
    phosphatase_path: Path = field(default_factory=Path, init=False)
    """The path to the 'phosphatase.bin' file used to gracefully terminate the MATLAB's runtimes locked into the data 
    acquisition mode by the presence of the 'kinase.bin' file."""

    def __post_init__(
        self,
    ) -> None:
        """Resolves the managed directory layout, creating any missing directory components."""
        # Resolves additional paths using the input root paths
        self.motion_estimator_path = self.persistent_data_path.joinpath("MotionEstimator.me")
        self.roi_path = self.persistent_data_path.joinpath("fov.roi")
        self.session_specific_path = self.meso_data_path.joinpath(self.session)
        self.mesoscope_data_path = self.meso_data_path.joinpath("mesoscope_data")
        self.kinase_path = self.mesoscope_data_path.joinpath("kinase.bin")
        self.phosphatase_path = self.mesoscope_data_path.joinpath("phosphatase.bin")

        # Ensures that the shared data directory and the persistent data directory exist.
        ensure_directory_exists(self.mesoscope_data_path)
        ensure_directory_exists(self.persistent_data_path)


@dataclass()
class _VRPCDestinations:
    """Defines the layout of the long-term data storage infrastructure mounted to the VRPC's filesystem via the SMB
    protocol used to store the session's data after acquisition.
    """

    nas_data_path: Path
    """The path to the session's data directory on the Synology NAS."""
    server_data_path: Path
    """The path to the session's data directory on the BioHPC server."""

    def __post_init__(self) -> None:
        """Resolves the managed directory layout, creating any missing directory components."""
        # Ensures all destination directories exist
        ensure_directory_exists(self.nas_data_path)
        ensure_directory_exists(self.server_data_path)


class MesoscopeData:
    """Defines the Mesoscope-VR data acquisition system's filesystem layout used to acquire and preprocess the target
    session's data.

    Args:
        session_data: The SessionData instance that defines the processed data acquisition session.

    Attributes:
        vrpc_data: Defines the layout of the session-specific VRPC's persistent data directory.
        scanimagepc_data: Defines the layout of the ScanImagePC's mesoscope data directory.
        destinations: Defines the layout of the long-term data storage infrastructure mounted to the VRPC's filesystem.
    """

    def __init__(self, system_configuration: MesoscopeSystemConfiguration, session_data: SessionData) -> None:
        # Unpacks session path nodes from the SessionData instance
        project = session_data.project_name
        animal = session_data.animal_id
        session = session_data.session_name

        # VRPC persistent data
        self.vrpc_data = _VRPCPersistentData(
            session_type=session_data.session_type,
            persistent_data_path=system_configuration.filesystem.root_directory.joinpath(
                project, animal, "persistent_data"
            ),
        )

        # ScanImagePC mesoscope data
        self.scanimagepc_data = _ScanImagePCData(
            session=session,
            meso_data_path=system_configuration.filesystem.mesoscope_directory,
            persistent_data_path=system_configuration.filesystem.mesoscope_directory.joinpath(
                project, animal, "persistent_data"
            ),
        )

        # Server and NAS (data storage)
        self.destinations = _VRPCDestinations(
            nas_data_path=system_configuration.filesystem.nas_directory.joinpath(project, animal, session),
            server_data_path=system_configuration.filesystem.server_directory.joinpath(project, animal, session),
        )


class RuntimeControlUI:
    """Provides the Graphical User Interface (GUI) that allows modifying certain Mesoscope-VR runtime parameters in real
    time.

    Notes:
        The UI runs in a parallel process and requires a single CPU core to support its runtime.

        Initializing the class does not start the UI process. Call the start() method before calling any other instance
        methods to start the UI process.

    Attributes:
        _data_array: The SharedMemoryArray instance used to bidirectionally transfer the data between the UI process
            and other runtime processes.
        _ui_process: The Process instance running the GUI cycle.
        _started: Tracks whether the UI process is running.
    """

    def __init__(self) -> None:
        # Defines the prototype array for the SharedMemoryArray initialization and sets the array elements to the
        # desired default state
        prototype = np.zeros(shape=11, dtype=np.uint32)
        prototype[_DataArrayIndex.PAUSE_STATE] = 1  # Ensures all runtimes start in a paused state
        prototype[_DataArrayIndex.GUIDANCE_ENABLED] = 0  # Initially disables guidance for all runtimes
        prototype[_DataArrayIndex.SHOW_REWARD] = 0  # Defaults to not showing reward collision boundary
        prototype[_DataArrayIndex.REWARD_VOLUME] = 5  # Preconfigures reward delivery to use 5 uL rewards

        # Initializes the SharedMemoryArray instance
        self._data_array = SharedMemoryArray.create_array(
            name="runtime_control_ui", prototype=prototype, exists_ok=True
        )

        # Defines but does not automatically start the UI process.
        self._ui_process = Process(target=self._run_ui_process, daemon=True)
        self._started = False

    def __del__(self) -> None:
        """Terminates the UI process and releases the instance's shared memory buffer when the instance is
        garbage-collected.
        """
        self.shutdown()

    def start(self) -> None:
        """Starts the remote UI process."""
        # If the instance is already started, aborts early
        if self._started:
            return

        # Starts the remote UI process.
        self._ui_process.start()

        # Connects to the shared memory array from the central runtime process and configures it to destroy the
        # shared memory buffer in case of an emergency (error) shutdown.
        self._data_array.connect()
        self._data_array.enable_buffer_destruction()

        # Marks the instance as started
        self._started = True

    def shutdown(self) -> None:
        """Shuts down the remote UI process and releases the instance's shared memory buffer."""
        # If the instance is already shut down, aborts early.
        if not self._started:
            return

        # Shuts down the remote UI process.
        if self._ui_process.is_alive():
            self._data_array[_DataArrayIndex.TERMINATION] = 1  # Sends the termination signal to the remote process
            self._ui_process.terminate()
            self._ui_process.join(timeout=2.0)

        # Terminates the shared memory array buffer.
        self._data_array.disconnect()
        self._data_array.destroy()

        # Marks the instance as shut down
        self._started = False

    def _run_ui_process(self) -> None:
        """Runs UI management cycle in a parallel process."""
        # Connects to the shared memory array from the remote process
        self._data_array.connect()

        # Creates and runs the Qt6 application in this process's main thread
        try:
            # Creates the GUI application
            app = QApplication(sys.argv)
            app.setApplicationName("Mesoscope-VR Control Panel")
            app.setOrganizationName("SunLab")

            # Sets Qt6 application-wide style
            app.setStyle("Fusion")

            # Creates the main application window
            window = _ControlUIWindow(self._data_array)
            window.show()

            # Runs the app
            app.exec()
        except Exception as e:
            message = (
                f"Unable to initialize the GUI application for the main runtime user interface. "
                f"Encountered the following error {e}."
            )
            console.error(message=message, error=RuntimeError)

        # Ensures proper UI shutdown when runtime encounters errors
        finally:
            self._data_array.disconnect()

    def set_pause_state(self, *, paused: bool) -> None:
        """Configures the GUI to reflect the current data acquisition session's runtime state.

        Args:
            paused: Determines whether the session is paused or running.
        """
        self._data_array[_DataArrayIndex.PAUSE_STATE] = 1 if paused else 0

    def set_guidance_state(self, *, enabled: bool) -> None:
        """Configures the GUI to reflect the data acquisition session's Virtual Reality task guidance state.

        Args:
            enabled: Determines whether the guidance mode is currently enabled.
        """
        self._data_array[_DataArrayIndex.GUIDANCE_ENABLED] = 1 if enabled else 0

    @property
    def exit_signal(self) -> bool:
        """Returns True if the user has requested the system to abort the data acquisition session's runtime."""
        exit_flag = bool(self._data_array[_DataArrayIndex.EXIT_SIGNAL])
        self._data_array[_DataArrayIndex.EXIT_SIGNAL] = 0
        return exit_flag

    @property
    def reward_signal(self) -> bool:
        """Returns True if the user has requested the system to deliver a water reward."""
        reward_flag = bool(self._data_array[_DataArrayIndex.REWARD_SIGNAL])
        self._data_array[_DataArrayIndex.REWARD_SIGNAL] = 0
        return reward_flag

    @property
    def speed_modifier(self) -> int:
        """Returns the current user-defined running speed threshold modifier."""
        return int(self._data_array[_DataArrayIndex.SPEED_MODIFIER])

    @property
    def duration_modifier(self) -> int:
        """Returns the current user-defined running epoch duration threshold modifier."""
        return int(self._data_array[_DataArrayIndex.DURATION_MODIFIER])

    @property
    def pause_runtime(self) -> bool:
        """Returns True if the user has requested the system to pause the data acquisition session's runtime."""
        return bool(self._data_array[_DataArrayIndex.PAUSE_STATE])

    @property
    def open_valve(self) -> bool:
        """Returns True if the user has requested the system to open the water delivery valve."""
        open_flag = bool(self._data_array[_DataArrayIndex.OPEN_VALVE])
        self._data_array[_DataArrayIndex.OPEN_VALVE] = 0
        return open_flag

    @property
    def close_valve(self) -> bool:
        """Returns True if the user has requested the system to close the water delivery valve."""
        close_flag = bool(self._data_array[_DataArrayIndex.CLOSE_VALVE])
        self._data_array[_DataArrayIndex.CLOSE_VALVE] = 0
        return close_flag

    @property
    def reward_volume(self) -> int:
        """Returns the current user-defined volume of water dispensed by the valve when delivering water rewards."""
        return int(self._data_array[_DataArrayIndex.REWARD_VOLUME])

    @property
    def enable_guidance(self) -> bool:
        """Returns True if the user has enabled the Virtual Reality task guidance mode."""
        return bool(self._data_array[_DataArrayIndex.GUIDANCE_ENABLED])

    @property
    def show_reward(self) -> bool:
        """Returns True if the user has enabled showing the Virtual Reality task guidance mode collision box to the
        animal.
        """
        return bool(self._data_array[_DataArrayIndex.SHOW_REWARD])


class _ControlUIWindow(QMainWindow):
    """Generates, renders, and maintains the Mesoscope-VR acquisition system's Graphical User Interface application
    window.

    Attributes:
        _data_array: The SharedMemoryArray instance used to bidirectionally transfer the data between the UI process
            and other runtime processes.
        _is_paused: Tracks whether the runtime is paused.
        _guidance_enabled: Tracks whether the Virtual Reality task guidance mode is enabled.
        _show_reward: Tracks whether the Virtual Reality guidance mode collision box is visible to the animal.
    """

    def __init__(self, data_array: SharedMemoryArray) -> None:
        super().__init__()  # Initializes the main window superclass

        # Defines internal attributes.
        self._data_array: SharedMemoryArray = data_array
        self._is_paused: bool = True
        self._guidance_enabled: bool = False
        self._show_reward: bool = False

        # Configures the window title
        self.setWindowTitle("Mesoscope-VR Control Panel")

        # Uses fixed size
        self.setFixedSize(450, 550)

        # Sets up the interactive UI
        self._setup_ui()
        self._setup_monitoring()

        # Applies Qt6-optimized styling and scaling parameters
        self._apply_qt6_styles()

    def _setup_ui(self) -> None:
        """Creates and arranges all UI elements."""
        # Initializes the main widget container
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Generates the central bounding box (the bounding box around all UI elements)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Runtime Control Group
        runtime_control_group = QGroupBox("Runtime Control")
        runtime_control_layout = QVBoxLayout(runtime_control_group)
        runtime_control_layout.setSpacing(6)

        # Runtime termination (exit) button
        self.exit_btn = QPushButton("✖ Terminate Runtime")
        self.exit_btn.setToolTip("Gracefully ends the runtime and initiates the shutdown procedure.")
        # noinspection PyUnresolvedReferences
        self.exit_btn.clicked.connect(self._exit_runtime)
        self.exit_btn.setObjectName("exitButton")

        # Runtime Pause / Unpause (resume) button
        self.pause_btn = QPushButton("▶️ Resume Runtime")
        self.pause_btn.setToolTip("Pauses or resumes the runtime.")
        # noinspection PyUnresolvedReferences
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.pause_btn.setObjectName("resumeButton")

        # Lick Guidance
        # Ensures the array is also set to the default value
        self.guidance_btn = QPushButton("🎯 Enable Guidance")
        self.guidance_btn.setToolTip("Toggles lick guidance mode on or off.")
        # noinspection PyUnresolvedReferences
        self.guidance_btn.clicked.connect(self._toggle_guidance)
        self.guidance_btn.setObjectName("guidanceButton")

        # Show / Hide Reward Collision Boundary
        self.reward_visibility_btn = QPushButton("👁️ Show Reward")
        self.reward_visibility_btn.setToolTip("Toggles reward collision boundary visibility on or off.")
        # noinspection PyUnresolvedReferences
        self.reward_visibility_btn.clicked.connect(self._toggle_reward_visibility)
        self.reward_visibility_btn.setObjectName("showRewardButton")

        # Configures the buttons to expand when the UI is resized, but use a fixed height of 35 points
        for btn in [self.exit_btn, self.pause_btn, self.guidance_btn, self.reward_visibility_btn]:
            btn.setMinimumHeight(35)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            runtime_control_layout.addWidget(btn)

        # Adds runtime status tracker to the same box
        self.runtime_status_label = QLabel("Runtime Status: ⏸️ Paused")
        self.runtime_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        runtime_status_font = QFont()
        runtime_status_font.setPointSize(35)
        runtime_status_font.setBold(True)
        self.runtime_status_label.setFont(runtime_status_font)
        self.runtime_status_label.setStyleSheet("QLabel { color: #f39c12; font-weight: bold; }")
        runtime_control_layout.addWidget(self.runtime_status_label)

        # Adds the runtime control box to the UI widget
        main_layout.addWidget(runtime_control_group)

        # Valve Control Group
        valve_group = QGroupBox("Valve Control")
        valve_layout = QVBoxLayout(valve_group)
        valve_layout.setSpacing(6)

        # Arranges valve control buttons in a horizontal layout
        valve_buttons_layout = QHBoxLayout()

        # Valve open
        self.valve_open_btn = QPushButton("🔓 Open")
        self.valve_open_btn.setToolTip("Opens the solenoid valve.")
        # noinspection PyUnresolvedReferences
        self.valve_open_btn.clicked.connect(self._open_valve)
        self.valve_open_btn.setObjectName("valveOpenButton")

        # Valve close
        self.valve_close_btn = QPushButton("🔒 Close")
        self.valve_close_btn.setToolTip("Closes the solenoid valve.")
        # noinspection PyUnresolvedReferences
        self.valve_close_btn.clicked.connect(self._close_valve)
        self.valve_close_btn.setObjectName("valveCloseButton")

        # Reward button
        self.reward_btn = QPushButton("● Reward")
        self.reward_btn.setToolTip("Delivers 5 uL of water through the solenoid valve.")
        # noinspection PyUnresolvedReferences
        self.reward_btn.clicked.connect(self._deliver_reward)
        self.reward_btn.setObjectName("rewardButton")

        # Configures the buttons to expand when the UI is resized, but use a fixed height of 35 points
        for btn in [self.valve_open_btn, self.valve_close_btn, self.reward_btn]:
            btn.setMinimumHeight(35)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            valve_buttons_layout.addWidget(btn)

        valve_layout.addLayout(valve_buttons_layout)

        # Valve status and volume control section - horizontal layout
        valve_status_layout = QHBoxLayout()
        valve_status_layout.setSpacing(6)

        # Volume control on the left
        volume_label = QLabel("Reward volume:")
        volume_label.setObjectName("volumeLabel")

        self.volume_spinbox = QDoubleSpinBox()
        self.volume_spinbox.setRange(1, 20)  # Ranges from 1 to 20
        self.volume_spinbox.setValue(5)  # Default value
        self.volume_spinbox.setDecimals(0)  # Integer precision
        self.volume_spinbox.setSuffix(" μL")  # Adds units suffix
        self.volume_spinbox.setToolTip("Sets water reward volume. Accepts values between 1 and 2 μL.")
        self.volume_spinbox.setMinimumHeight(30)
        # noinspection PyUnresolvedReferences
        self.volume_spinbox.valueChanged.connect(self._update_reward_volume)

        # Adds volume controls to the left side
        valve_status_layout.addWidget(volume_label)
        valve_status_layout.addWidget(self.volume_spinbox)

        # Adds the valve status tracker on the right
        self.valve_status_label = QLabel("Valve: 🔒 Closed")
        self.valve_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        valve_status_font = QFont()
        valve_status_font.setPointSize(35)
        valve_status_font.setBold(True)
        self.valve_status_label.setFont(valve_status_font)
        self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")
        valve_status_layout.addWidget(self.valve_status_label)

        # Add the horizontal status layout to the main valve layout
        valve_layout.addLayout(valve_status_layout)

        # Adds the valve control box to the UI widget
        main_layout.addWidget(valve_group)

        # Adds Run Training controls in a horizontal layout
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(6)

        # Running Speed Threshold Control Group
        speed_group = QGroupBox("Speed Threshold")
        speed_layout = QVBoxLayout(speed_group)

        # Speed Modifier
        speed_status_label = QLabel("Current Modifier:")
        speed_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_status_label.setStyleSheet("QLabel { font-weight: bold; color: #34495e; }")
        speed_layout.addWidget(speed_status_label)
        self.speed_spinbox = QDoubleSpinBox()
        self.speed_spinbox.setRange(-1000, 1000)  # Factoring in the step of 0.01, this allows -20 to +20 cm/s
        self.speed_spinbox.setValue(0)  # Default value
        self.speed_spinbox.setDecimals(0)  # Integer precision
        self.speed_spinbox.setToolTip("Sets the running speed threshold modifier value.")
        self.speed_spinbox.setMinimumHeight(30)
        # noinspection PyUnresolvedReferences
        self.speed_spinbox.valueChanged.connect(self._update_speed_modifier)
        speed_layout.addWidget(self.speed_spinbox)

        # Running Duration Threshold Control Group
        duration_group = QGroupBox("Duration Threshold")
        duration_layout = QVBoxLayout(duration_group)

        # Duration modifier
        duration_status_label = QLabel("Current Modifier:")
        duration_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        duration_status_label.setStyleSheet("QLabel { font-weight: bold; color: #34495e; }")
        duration_layout.addWidget(duration_status_label)
        self.duration_spinbox = QDoubleSpinBox()
        self.duration_spinbox.setRange(-1000, 1000)  # Factoring in the step of 0.01, this allows -20 to +20 s
        self.duration_spinbox.setValue(0)  # Default value
        self.duration_spinbox.setDecimals(0)  # Integer precision
        self.duration_spinbox.setToolTip("Sets the running duration threshold modifier value.")
        # noinspection PyUnresolvedReferences
        self.duration_spinbox.valueChanged.connect(self._update_duration_modifier)
        duration_layout.addWidget(self.duration_spinbox)

        # Adds speed and duration threshold modifiers to the main UI widget
        controls_layout.addWidget(speed_group)
        controls_layout.addWidget(duration_group)
        main_layout.addLayout(controls_layout)

    def _apply_qt6_styles(self) -> None:
        """Applies optimized styling to all UI elements managed by this instance."""
        self.setStyleSheet("""
                    QMainWindow {
                        background-color: #ecf0f1;
                    }

                    QGroupBox {
                        font-weight: bold;
                        font-size: 14pt;
                        border: 2px solid #bdc3c7;
                        border-radius: 8px;
                        margin: 25px 6px 6px 6px;
                        padding-top: 10px;
                        background-color: #ffffff;
                    }

                    QGroupBox::title {
                        subcontrol-origin: margin;
                        subcontrol-position: top center;
                        left: 0px;
                        right: 0px;
                        padding: 0 8px 0 8px;
                        color: #2c3e50;
                        background-color: transparent;
                        border: none;
                    }

                    QPushButton {
                        background-color: #ffffff;
                        border: 2px solid #bdc3c7;
                        border-radius: 6px;
                        padding: 6px 8px;
                        font-size: 12pt;
                        font-weight: 500;
                        color: #2c3e50;
                        min-height: 20px;
                    }

                    QPushButton:hover {
                        background-color: #f8f9fa;
                        border-color: #3498db;
                        color: #2980b9;
                    }

                    QPushButton:pressed {
                        background-color: #e9ecef;
                        border-color: #2980b9;
                    }

                    QPushButton#exitButton {
                        background-color: #e74c3c;
                        color: white;
                        border-color: #c0392b;
                        font-weight: bold;
                    }

                    QPushButton#exitButton:hover {
                        background-color: #c0392b;
                        border-color: #a93226;
                    }

                    QPushButton#pauseButton {
                        background-color: #f39c12;
                        color: white;
                        border-color: #e67e22;
                        font-weight: bold;
                    }

                    QPushButton#pauseButton:hover {
                        background-color: #e67e22;
                        border-color: #d35400;
                    }

                    QPushButton#resumeButton {
                        background-color: #27ae60;
                        color: white;
                        border-color: #229954;
                        font-weight: bold;
                    }

                    QPushButton#resumeButton:hover {
                        background-color: #229954;
                        border-color: #1e8449;
                    }

                    QPushButton#valveOpenButton {
                        background-color: #27ae60;
                        color: white;
                        border-color: #229954;
                        font-weight: bold;
                    }

                    QPushButton#valveOpenButton:hover {
                        background-color: #229954;
                        border-color: #1e8449;
                    }

                    QPushButton#valveCloseButton {
                        background-color: #e67e22;
                        color: white;
                        border-color: #d35400;
                        font-weight: bold;
                    }

                    QPushButton#valveCloseButton:hover {
                        background-color: #d35400;
                        border-color: #ba4a00;
                    }
                    
                    QPushButton#rewardButton {
                        background-color: #3498db;
                        color: white;
                        border-color: #2980b9;
                        font-weight: bold;
                    }

                    QPushButton#rewardButton:hover {
                        background-color: #2980b9;
                        border-color: #21618c;
                    }

                    QLabel {
                        color: #2c3e50;
                        font-size: 12pt;
                    }
                    
                    QLabel#volumeLabel {
                        color: #2c3e50;
                        font-size: 12pt;
                        font-weight: bold;
                    }
    
                    QDoubleSpinBox {
                        border: 2px solid #bdc3c7;
                        border-radius: 4px;
                        padding: 4px 8px;
                        font-weight: bold;
                        font-size: 12pt;
                        background-color: white;
                        color: #2c3e50;
                        min-height: 20px;
                    }
    
                    QDoubleSpinBox:focus {
                        border-color: #3498db;
                    }
    
                    QDoubleSpinBox::up-button {
                        subcontrol-origin: border;
                        subcontrol-position: top right;
                        width: 20px;
                        background-color: #f8f9fa;
                        border: 1px solid #bdc3c7;
                        border-top-right-radius: 4px;
                        border-bottom: none;
                    }
    
                    QDoubleSpinBox::up-button:hover {
                        background-color: #e9ecef;
                        border-color: #3498db;
                    }
    
                    QDoubleSpinBox::up-button:pressed {
                        background-color: #dee2e6;
                    }
    
                    QDoubleSpinBox::up-arrow {
                        image: none;
                        border-left: 4px solid transparent;
                        border-right: 4px solid transparent;
                        border-bottom: 6px solid #2c3e50;
                        width: 0px;
                        height: 0px;
                    }
    
                    QDoubleSpinBox::down-button {
                        subcontrol-origin: border;
                        subcontrol-position: bottom right;
                        width: 20px;
                        background-color: #f8f9fa;
                        border: 1px solid #bdc3c7;
                        border-bottom-right-radius: 4px;
                        border-top: none;
                    }
    
                    QDoubleSpinBox::down-button:hover {
                        background-color: #e9ecef;
                        border-color: #3498db;
                    }
    
                    QDoubleSpinBox::down-button:pressed {
                        background-color: #dee2e6;
                    }
    
                    QDoubleSpinBox::down-arrow {
                        image: none;
                        border-left: 4px solid transparent;
                        border-right: 4px solid transparent;
                        border-top: 6px solid #2c3e50;
                        width: 0px;
                        height: 0px;
                    }
    
                    QSlider::groove:horizontal {
                        border: 1px solid #bdc3c7;
                        height: 8px;
                        background: #ecf0f1;
                        margin: 2px 0;
                        border-radius: 4px;
                    }
    
                    QSlider::handle:horizontal {
                        background: #3498db;
                        border: 2px solid #2980b9;
                        width: 20px;
                        margin: -6px 0;
                        border-radius: 10px;
                    }
    
                    QSlider::handle:horizontal:hover {
                        background: #2980b9;
                        border-color: #21618c;
                    }
    
                    QSlider::handle:horizontal:pressed {
                        background: #21618c;
                    }
    
                    QSlider::sub-page:horizontal {
                        background: #3498db;
                        border: 1px solid #2980b9;
                        height: 8px;
                        border-radius: 4px;
                    }
    
                    QSlider::add-page:horizontal {
                        background: #ecf0f1;
                        border: 1px solid #bdc3c7;
                        height: 8px;
                        border-radius: 4px;
                    }
    
                    QSlider::groove:vertical {
                        border: 1px solid #bdc3c7;
                        width: 8px;
                        background: #ecf0f1;
                        margin: 0 2px;
                        border-radius: 4px;
                    }
    
                    QSlider::handle:vertical {
                        background: #3498db;
                        border: 2px solid #2980b9;
                        height: 20px;
                        margin: 0 -6px;
                        border-radius: 10px;
                    }
    
                    QSlider::handle:vertical:hover {
                        background: #2980b9;
                        border-color: #21618c;
                    }
    
                    QSlider::handle:vertical:pressed {
                        background: #21618c;
                    }
    
                    QSlider::sub-page:vertical {
                        background: #ecf0f1;
                        border: 1px solid #bdc3c7;
                        width: 8px;
                        border-radius: 4px;
                    }
    
                    QSlider::add-page:vertical {
                        background: #3498db;
                        border: 1px solid #2980b9;
                        width: 8px;
                        border-radius: 4px;
                    }
                    
                    QPushButton#guidanceButton {
                    background-color: #9b59b6;
                    color: white;
                    border-color: #8e44ad;
                    font-weight: bold;
                    }
                    
                    QPushButton#guidanceButton:hover {
                        background-color: #8e44ad;
                        border-color: #7d3c98;
                    }
                    
                    QPushButton#guidanceDisableButton {
                        background-color: #95a5a6;
                        color: white;
                        border-color: #7f8c8d;
                        font-weight: bold;
                    }
                    
                    QPushButton#guidanceDisableButton:hover {
                        background-color: #7f8c8d;
                        border-color: #6c7b7d;
                    }
                    QPushButton#hideRewardButton {
                        background-color: #e74c3c;
                        color: white;
                        border-color: #c0392b;
                        font-weight: bold;
                    }
                    
                    QPushButton#hideRewardButton:hover {
                        background-color: #c0392b;
                        border-color: #a93226;
                    }
                    
                    QPushButton#showRewardButton {
                        background-color: #27ae60;
                        color: white;
                        border-color: #229954;
                        font-weight: bold;
                    }
                    
                    QPushButton#showRewardButton:hover {
                        background-color: #229954;
                        border-color: #1e8449;
                    }
                """)

    def _setup_monitoring(self) -> None:
        """Sets up a QTimer to monitor the runtime termination status."""
        self.monitor_timer = QTimer(self)
        # noinspection PyUnresolvedReferences
        self.monitor_timer.timeout.connect(self._check_external_state)
        self.monitor_timer.start(100)  # Checks every 100 ms

    def _check_external_state(self) -> None:
        """Checks the state of externally addressable UI elements and updates the managed GUI to reflect the
        externally driven changes.
        """
        # noinspection PyBroadException
        try:
            # If the termination flag has been set to 1, terminates the GUI process
            if self._data_array[_DataArrayIndex.TERMINATION] == 1:
                self.close()

            # Checks for external pause state changes and, if necessary, updates the GUI to reflect the current
            # runtime state (running or paused).
            external_pause_state = bool(self._data_array[_DataArrayIndex.PAUSE_STATE])
            if external_pause_state != self._is_paused:
                # External pause state changed, update UI accordingly
                self._is_paused = external_pause_state
                self._update_pause_ui()

            # Checks for external guidance state changes and, if necessary, updates the GUI to reflect the current
            # guidance state (enabled or disabled).
            external_guidance_state = bool(self._data_array[_DataArrayIndex.GUIDANCE_ENABLED])
            if external_guidance_state != self._guidance_enabled:
                # External guidance state changed, update UI accordingly
                self._guidance_enabled = external_guidance_state
                self._update_guidance_ui()
        except Exception:
            self.close()

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802
        """Handles GUI window close events.

        Args:
            event: The Qt-generated window shutdown event instance.
        """
        # Sends a runtime termination signal via the SharedMemoryArray before accepting the close event.
        # noinspection PyBroadException
        with contextlib.suppress(Exception):
            self._data_array[_DataArrayIndex.TERMINATION] = 1
        if event is not None:
            event.accept()

    def _exit_runtime(self) -> None:
        """Instructs the system to terminate the runtime."""
        previous_status = self.runtime_status_label.text()
        style = self.runtime_status_label.styleSheet()
        self._data_array[_DataArrayIndex.EXIT_SIGNAL] = 1
        self.runtime_status_label.setText("✖ Exit signal sent")
        self.runtime_status_label.setStyleSheet("QLabel { color: #e74c3c; font-weight: bold; }")
        self.exit_btn.setText("✖ Exit Requested")
        self.exit_btn.setEnabled(False)

        # Resets the button after 2 seconds
        QTimer.singleShot(2000, lambda: self.exit_btn.setText("✖ Terminate Runtime"))
        QTimer.singleShot(2000, lambda: self.exit_btn.setStyleSheet("QLabel { color: #c0392b; font-weight: bold; }"))
        QTimer.singleShot(2000, lambda: self.exit_btn.setEnabled(True))

        # Restores the status back to the previous state
        QTimer.singleShot(2000, lambda: self.runtime_status_label.setText(previous_status))
        QTimer.singleShot(2000, lambda: self.runtime_status_label.setStyleSheet(style))

    def _deliver_reward(self) -> None:
        """Instructs the system to deliver a water reward to the animal."""
        # Sends the reward command via the SharedMemoryArray and temporarily sets the statsu to indicate that the
        # reward is sent.
        self._data_array[_DataArrayIndex.REWARD_SIGNAL] = 1
        self.valve_status_label.setText("Reward: 🟢 Sent")
        self.valve_status_label.setStyleSheet("QLabel { color: #3498db; font-weight: bold; }")

        # Resets the status to 'closed' after 1 second using the Qt6 single shot timer. This is realistically the
        # longest time the system would take to start and finish delivering the reward
        QTimer.singleShot(2000, lambda: self.valve_status_label.setText("Valve: 🔒 Closed"))
        QTimer.singleShot(
            2000, lambda: self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")
        )

    def _open_valve(self) -> None:
        """Instructs the system to open the water delivery valve."""
        self._data_array[_DataArrayIndex.OPEN_VALVE] = 1
        self.valve_status_label.setText("Valve: 🔓 Opened")
        self.valve_status_label.setStyleSheet("QLabel { color: #27ae60; font-weight: bold; }")

    def _close_valve(self) -> None:
        """Instructs the system to close the water delivery valve."""
        self._data_array[_DataArrayIndex.CLOSE_VALVE] = 1
        self.valve_status_label.setText("Valve: 🔒 Closed")
        self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")

    def _toggle_pause(self) -> None:
        """Instructs the system to pause or resume the data acquisition session's runtime."""
        self._is_paused = not self._is_paused
        self._data_array[_DataArrayIndex.PAUSE_STATE] = 1 if self._is_paused else 0
        self._update_pause_ui()

    def _update_reward_volume(self) -> None:
        """Updates the volume used by the system when delivering water rewards to match the current GUI
        configuration.
        """
        self._data_array[_DataArrayIndex.REWARD_VOLUME] = int(self.volume_spinbox.value())

    def _update_speed_modifier(self) -> None:
        """Updates the running speed threshold modifier to match the current GUI configuration."""
        self._data_array[_DataArrayIndex.SPEED_MODIFIER] = int(self.speed_spinbox.value())

    def _update_duration_modifier(self) -> None:
        """Updates the running epoch duration modifier to match the current GUI configuration."""
        self._data_array[_DataArrayIndex.DURATION_MODIFIER] = int(self.duration_spinbox.value())

    @staticmethod
    def _refresh_button_style(button: QPushButton) -> None:
        """Refreshes button styles after object name change."""
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _update_guidance_ui(self) -> None:
        """Updates the GUI to reflect the current Virtual Reality task guidance state."""
        if self._guidance_enabled:
            self.guidance_btn.setText("🚫 Disable Guidance")
            self.guidance_btn.setObjectName("guidanceDisableButton")
        else:
            self.guidance_btn.setText("🎯 Enable Guidance")
            self.guidance_btn.setObjectName("guidanceButton")

        # Refreshes styles after object name change
        self._refresh_button_style(button=self.guidance_btn)

    def _toggle_guidance(self) -> None:
        """Instructs the system to enable or disable the Virtual Reality task guidance mode."""
        self._guidance_enabled = not self._guidance_enabled
        self._data_array[_DataArrayIndex.GUIDANCE_ENABLED] = 1 if self._guidance_enabled else 0
        self._update_guidance_ui()

    def _update_pause_ui(self) -> None:
        """Updates the GUI to reflect the current data acquisition runtime pause state."""
        if self._is_paused:
            self.pause_btn.setText("▶️ Resume Runtime")
            self.pause_btn.setObjectName("resumeButton")
            self.runtime_status_label.setText("Runtime Status: ⏸️ Paused")
            self.runtime_status_label.setStyleSheet("QLabel { color: #f39c12; font-weight: bold; }")
        else:
            self.pause_btn.setText("⏸️ Pause Runtime")
            self.pause_btn.setObjectName("pauseButton")
            self.runtime_status_label.setText("Runtime Status: 🟢 Running")
            self.runtime_status_label.setStyleSheet("QLabel { color: #27ae60; font-weight: bold; }")

        # Refresh styles after object name change
        self._refresh_button_style(button=self.pause_btn)

    def _toggle_reward_visibility(self) -> None:
        """Instructs the system to show or hide the Virtual Reality guidance mode collision box."""
        self._show_reward = not self._show_reward
        if self._show_reward:
            self._data_array[_DataArrayIndex.SHOW_REWARD] = 1
            self.reward_visibility_btn.setText("🙈 Hide Reward")
            self.reward_visibility_btn.setObjectName("hideRewardButton")
        else:
            self._data_array[_DataArrayIndex.SHOW_REWARD] = 0
            self.reward_visibility_btn.setText("👁️ Show Reward")
            self.reward_visibility_btn.setObjectName("showRewardButton")

        # Refreshes styles after object name change
        self._refresh_button_style(button=self.reward_visibility_btn)


class CachedMotifDecomposer:
    """Caches the flattened trial cue sequence motif data between multiple motif decomposition runtimes.

    Attributes:
        _cached_motifs: Stores the original trial motifs used for decomposition.
        _cached_flat_data: Stores the flattened motif data structure, optimized for numba-accelerated computations.
        _cached_distances: Stores the distances of each trial motif, in centimeters.
    """

    def __init__(self) -> None:
        self._cached_motifs: list[NDArray[np.uint8]] | None = None
        self._cached_flat_data: (
            tuple[NDArray[np.uint8], NDArray[np.int32], NDArray[np.int32], NDArray[np.int32]] | None
        ) = None
        self._cached_distances: NDArray[np.float32] | None = None

    def prepare_motif_data(
        self, trial_motifs: list[NDArray[np.uint8]], trial_distances: list[float]
    ) -> tuple[NDArray[np.uint8], NDArray[np.int32], NDArray[np.int32], NDArray[np.int32], NDArray[np.float32]]:
        """Prepares and caches the flattened motif data for faster cue sequence-to-trial decomposition (conversion).

        Args:
            trial_motifs: The trial motifs (wall cue sequences) to decompose.
            trial_distances: The trial motif distances, in centimeters.

        Returns:
            A tuple with five elements. The first element is the flattened array that stores all motifs. The second
            element is the array that stores the starting indices of each motif in the flattened array. The third
            element is the array that stores the length of each motif, in cues. The fourth element is the array
            that stores the original indices of motifs before sorting. The fifth element is the array of trial distances
            in centimeters.
        """
        # Checks if the class already contains cached data for the input motifs. In this case, returns the cached data.
        if self._cached_motifs is not None and len(self._cached_motifs) == len(trial_motifs):
            # Carries out deep comparison of motif arrays
            all_equal = all(
                np.array_equal(cached, current)
                for cached, current in zip(self._cached_motifs, trial_motifs, strict=True)
            )
            if all_equal and self._cached_flat_data is not None and self._cached_distances is not None:
                # noinspection PyRedundantParentheses, PyTypeChecker
                return (*self._cached_flat_data, self._cached_distances)

        # Otherwise, prepares flattened motif data:
        # Sorts motifs by length (longest first)
        motif_data: list[tuple[int, NDArray[np.uint8], int]] = [
            (i, motif, len(motif)) for i, motif in enumerate(trial_motifs)
        ]
        motif_data.sort(key=lambda x: x[2], reverse=True)

        # Calculates total size needed to represent all motifs in an array.
        total_size: int = sum(len(motif) for motif in trial_motifs)
        num_motifs: int = len(trial_motifs)

        # Creates arrays with specified dtypes.
        motifs_flat: NDArray[np.uint8] = np.zeros(total_size, dtype=np.uint8)
        motif_starts: NDArray[np.int32] = np.zeros(num_motifs, dtype=np.int32)
        motif_lengths: NDArray[np.int32] = np.zeros(num_motifs, dtype=np.int32)
        motif_indices: NDArray[np.int32] = np.zeros(num_motifs, dtype=np.int32)

        # Fills the arrays
        current_pos: int = 0
        for i, (orig_idx, motif, length) in enumerate(motif_data):
            # Ensures motifs are stored as uint8
            motif_uint8 = motif.astype(np.uint8) if motif.dtype != np.uint8 else motif
            motifs_flat[current_pos : current_pos + length] = motif_uint8
            motif_starts[i] = current_pos
            motif_lengths[i] = length
            motif_indices[i] = orig_idx
            current_pos += length

        # Converts distances to float32 type
        distances_array: NDArray[np.float32] = np.array(trial_distances, dtype=np.float32)

        # Caches the results
        self._cached_motifs = [motif.copy() for motif in trial_motifs]
        self._cached_flat_data = (motifs_flat, motif_starts, motif_lengths, motif_indices)
        self._cached_distances = distances_array

        # noinspection PyTypeChecker, PyRedundantParentheses
        return (*self._cached_flat_data, distances_array)
