"""This module provides additional tools and classes used by other modules of the mesoscope_vr package. Primarily, this
includes various dataclasses specific to the Mesoscope-VR systems and utility functions used by other package modules.
The contents of this module are not intended to be used outside the mesoscope_vr package.
"""

import sys
from pathlib import Path
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
    """Verifies that the current data acquisition system is the Mesoscope-VR and returns its configuration data.

    Raises:
        ValueError: If the local data acquisition system is not a Mesoscope-VR system.
    """
    system_configuration = get_system_configuration_data()
    if not isinstance(system_configuration, MesoscopeSystemConfiguration):
        message = (
            "Unable to instantiate the MesoscopeData class, as the local data acquisition system is not a "
            "Mesoscope-VR system. This either indicates a user error (calling incorrect Data class) or local data "
            "acquisition system misconfiguration. To reconfigured the data-acquisition system, use the "
            "sl-create-system-config' CLI command."
        )
        console.error(message, error=ValueError)
    return system_configuration


@dataclass()
class _VRPCPersistentData:
    """Stores the paths to the directories and files that make up the 'persistent_data' directory on the VRPC.

    VRPC persistent data directory is used to preserve configuration data, such as the positions of Zaber motors and
    Meososcope objective, so that they can be reused across sessions of the same animals. The data in this directory
    is read at the beginning of each session and replaced at the end of each session.
    """

    session_type: str
    """Stores the type of the Mesoscope-VR-compatible session for which this additional dataclass is instantiated. This 
    is used to resolve the cached session_Descriptor instance, as different session types use different descriptor 
    files."""
    persistent_data_path: Path
    """Stores the path to the project- and animal-specific 'persistent_data' directory relative to the VRPC root."""
    zaber_positions_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the Zaber motor positions snapshot generated at the end of the previous session runtime. This 
    is used to automatically restore all Zaber motors to the same position across all sessions."""
    mesoscope_positions_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the Mesoscope positions snapshot generated at the end of the previous session runtime. This 
    is used to help the user to (manually) restore the Mesoscope to the same position across all sessions."""
    session_descriptor_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the session_descriptor.yaml file generated at the end of the previous session runtime. This 
    is used to automatically restore session runtime parameters used during the previous session. Primarily, this is 
    used during animal training."""
    window_screenshot_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the window_screenshot.png file. This is a screenshot of the red-dot alignment, the 
    ScanImage acquisition parameters, and the state of the imaged ROIs from the previous session. The screenshots are 
    used to restore the imaging parameters to the same state as used during the previous session."""

    def __post_init__(self) -> None:
        # Resolves paths that can be derived from the root path.
        self.zaber_positions_path = self.persistent_data_path.joinpath("zaber_positions.yaml")
        self.mesoscope_positions_path = self.persistent_data_path.joinpath("mesoscope_positions.yaml")
        self.window_screenshot_path = self.persistent_data_path.joinpath("window_screenshot.png")

        # Resolves the session descriptor path based on the session type.
        if self.session_type == SessionTypes.LICK_TRAINING:
            self.session_descriptor_path = self.persistent_data_path.joinpath("lick_training_session_descriptor.yaml")
        elif self.session_type == SessionTypes.RUN_TRAINING:
            self.session_descriptor_path = self.persistent_data_path.joinpath("run_training_session_descriptor.yaml")
        elif self.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
            self.session_descriptor_path = self.persistent_data_path.joinpath(
                "mesoscope_experiment_session_descriptor.yaml"
            )
        elif self.session_type == SessionTypes.WINDOW_CHECKING:
            self.session_descriptor_path = self.persistent_data_path.joinpath("window_checking_session_descriptor.yaml")

        else:  # Raises an error for unsupported session types
            message = (
                f"Unsupported session type '{self.session_type}' encountered when initializing additional path "
                f"dataclasses for the Mesoscope-VR data acquisition system. Supported session types are "
                f"'lick training', 'run training', 'window checking' and 'mesoscope experiment'."
            )
            console.error(message, error=ValueError)

        # Ensures that the target persistent directory exists
        ensure_directory_exists(self.persistent_data_path)


@dataclass()
class _ScanImagePCData:
    """Stores the paths to the directories and files that make up the 'meso_data' directory on the ScanImagePC.

    During runtime, the ScanImagePC should organize all collected data under this root directory. During preprocessing,
    the VRPC uses SMB to access the data in this directory and merge it into the 'raw_data' session directory. The root
    ScanImagePC directory also includes the persistent_data directories for all animals and projects whose data is
    acquired via the Mesoscope-VR system.
    """

    session_name: str
    """Stores the name of the session for which this data management class is instantiated. This is used to rename the 
    general mesoscope data directory on the ScanImagePC to include the session-specific name."""
    meso_data_path: Path
    """Stores the path to the root ScanImagePC data directory, mounted to the VRPC filesystem via the SMB or equivalent 
    protocol. All mesoscope-generated data is stored under this root directory before it is merged into the VRPC-managed
    raw_data directory of each session."""
    persistent_data_path: Path
    """Stores the path to the project- and animal-specific 'persistent_data' directory relative to the ScanImagePC 
    root directory ('meso-data' directory)."""
    mesoscope_data_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the 'default' mesoscope_data directory. All experiment sessions across all animals and 
    projects use the same mesoscope_data directory to save the data generated by the mesoscope via ScanImage 
    software. This simplifies ScanImagePC configuration process during runtime, as all data is always saved in the same
    directory. During preprocessing, the data is moved from the default directory first into a session-specific 
    ScanImagePC directory and then into the VRPC raw_data session directory."""
    session_specific_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the session-specific data directory. This directory is generated at the end of each experiment
    runtime to prepare mesoscope data for being moved to the VRPC-managed raw_data directory and to reset the 'default' 
    mesoscope_data directory for the next session's runtime."""
    ubiquitin_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the 'ubiquitin.bin' file. This file is automatically generated inside the session-specific 
    data directory after its contents are safely transferred to the VRPC as part of preprocessing. During redundant data
    removal step of preprocessing, the VRPC searches for directories marked with ubiquitin.bin and deletes them from the
    ScanImagePC filesystem."""
    motion_estimator_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the 'reference' motion estimator file generated during the first experiment session of each 
    animal. This file is kept on the ScanImagePC to image the same population of cells across all experiment 
    sessions."""
    roi_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the 'reference' fov.roi file generated during the first experiment session of each animal. 
    This file is kept on the ScanImagePC in addition to the motion estimator file. It contains the snapshot of the 
    ROI used during imaging."""
    kinase_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the 'kinase.bin' file. The MATLAB runtime function (setupAcquisition.m) that runs on the 
    ScanImagePC uses the presence of the file as a signal that the VRPC is currently acquiring a session. In turn, this
    locks the function into data acquisition mode until the kinase marker is removed by the VRPC."""
    phosphatase_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the 'phosphatase.bin' file. This marker is used together with the 'kinase.bin' marker. The 
    presence of the 'phosphatase.bin' file is used to disable the acquisition state lock and allows the MATLAB runtime 
    function to end its runtime even if the acquisition has never been started. This is used to gracefully end runtimes
    that encountered an error during the initialization process."""

    def __post_init__(
        self,
    ) -> None:
        # Resolves additional paths using the input root paths
        self.motion_estimator_path = self.persistent_data_path.joinpath("MotionEstimator.me")
        self.roi_path = self.persistent_data_path.joinpath("fov.roi")
        self.session_specific_path = self.meso_data_path.joinpath(self.session_name)
        self.ubiquitin_path = self.session_specific_path.joinpath("ubiquitin.bin")
        self.mesoscope_data_path = self.meso_data_path.joinpath("mesoscope_data")
        self.kinase_path = self.mesoscope_data_path.joinpath("kinase.bin")
        self.phosphatase_path = self.mesoscope_data_path.joinpath("phosphatase.bin")

        # Ensures that the shared data directory and the persistent data directory exist.
        ensure_directory_exists(self.mesoscope_data_path)
        ensure_directory_exists(self.persistent_data_path)


@dataclass()
class _VRPCDestinations:
    """Stores the paths to the VRPC filesystem-mounted directories of the Synology NAS and BioHPC server.

    The paths from this section are primarily used to transfer preprocessed data to the long-term storage destinations.
    """

    nas_raw_data_path: Path
    """Stores the path to the session's raw_data directory on the Synology NAS, which is mounted to the VRPC via the 
    SMB or equivalent protocol."""
    server_raw_data_path: Path
    """Stores the path to the session's raw_data directory on the BioHPC server, which is mounted to the VRPC via the 
    SMB or equivalent protocol."""
    server_processed_data_path: Path
    """Stores the path to the session's processed_data directory on the BioHPC server, which is mounted to the VRPC via 
    the SMB or equivalent protocol."""
    telomere_path: Path = field(default_factory=Path, init=False)
    """Stores the path to the session's telomere.bin marker. This marker is generated as part of data preprocessing on 
    the VRPC and can be removed by the BioHPC server to notify the VRPC that the server received preprocessed in a 
    compromised (damaged) state. If the telomere.bin file is present on the BioHPC server after the VRPC instructs the
    server to verify the integrity opf the transferred data, the VRPC concludes that the data was transferred intact and
    removes (purges) the local copy of raw_data."""

    def __post_init__(self) -> None:
        # Resolves the server-side telomere.bin marker path using the root directory.
        self.telomere_path = self.server_raw_data_path.joinpath("telomere.bin")

        # Ensures all destination directories exist
        ensure_directory_exists(self.nas_raw_data_path)
        ensure_directory_exists(self.server_raw_data_path)
        ensure_directory_exists(self.server_processed_data_path)


class MesoscopeData:
    """This works together with the SessionData class to define additional filesystem paths used by the Mesoscope-VR
    data acquisition system during runtime.

    Specifically, the paths from this class are used during both data acquisition and preprocessing to work with
    the managed session's data across the machines (PCs) that make up the acquisition system and long-term storage
    infrastructure.

    Args:
        session_data: The SessionData instance for the managed session.

    Attributes:
        vrpc_persistent_data: Stores paths to files inside the VRPC persistent_data directory for the managed session's
            project and animal.
        scanimagepc_data: Stores paths to all ScanImagePC (Mesoscope PC) files and directories used during data
            acquisition and processing.
        destinations: Stores paths to the long-term data storage destinations.
    """

    def __init__(self, session_data: SessionData):
        # Prevents this class from being instantiated on any acquisition system other than the Mesoscope-VR system.
        system_configuration = get_system_configuration()

        # Unpacks session paths nodes from the SessionData instance
        project = session_data.project_name
        animal = session_data.animal_id
        session = session_data.session_name

        # Instantiates additional path data classes
        # noinspection PyArgumentList
        self.vrpc_persistent_data = _VRPCPersistentData(
            session_type=session_data.session_type,
            persistent_data_path=system_configuration.paths.root_directory.joinpath(project, animal, "persistent_data"),
        )

        # noinspection PyArgumentList
        self.scanimagepc_data = _ScanImagePCData(
            session_name=session,
            meso_data_path=system_configuration.paths.mesoscope_directory,
            persistent_data_path=system_configuration.paths.mesoscope_directory.joinpath(
                project, animal, "persistent_data"
            ),
        )

        # noinspection PyArgumentList
        self.destinations = _VRPCDestinations(
            nas_raw_data_path=system_configuration.paths.nas_directory.joinpath(project, animal, session, "raw_data"),
            server_raw_data_path=system_configuration.paths.server_storage_directory.joinpath(
                project, animal, session, "raw_data"
            ),
            server_processed_data_path=system_configuration.paths.server_working_directory.joinpath(
                project, animal, session, "processed_data"
            ),
        )


class RuntimeControlUI:
    """Provides a real-time Graphical User Interface (GUI) that allows interactively controlling certain Mesoscope-VR
    runtime parameters.

    The UI itself runs in a parallel process and communicates with an instance of this class via the SharedMemoryArray
    instance. This optimizes the UI's responsiveness without overburdening the main thread that runs the task logic and
    the animal performance visualization.

    Notes:
        This class is specialized to work with the Qt6 framework. In the future, it may be refactored to support the Qt6
        framework.

        The UI starts the runtime in the 'paused' state to allow the user to check the valve and all other runtime
        components before formally starting the runtime.

    Attributes:
        _data_array: A SharedMemoryArray used to store the data recorded by the remote UI process.
        _ui_process: The Process instance running the Qt6 UI.
        _started: A static flag used to prevent the __del__ method from shutting down an already terminated instance.

    Notes:
        Since version 3.0.0, calling the initializer does not start the IO process. Call the start() method to finish
        initializing all UI assets.
    """

    def __init__(self) -> None:
        self._data_array = SharedMemoryArray.create_array(
            name="runtime_control_ui", prototype=np.zeros(shape=11, dtype=np.int32), exist_ok=True
        )

        # Configures certain array elements to specific initialization values
        self._data_array.write_data(index=8, data=np.int32(5))  # Preconfigures reward delivery to use 5 uL rewards
        self._data_array.write_data(index=10, data=np.int32(0))  # Defaults to not showing reward collision boundary
        self._data_array.write_data(index=9, data=np.int32(0))  # Initially disables guidance for all runtimes
        self._data_array.write_data(index=5, data=np.int32(1))  # Ensures all runtimes start in a paused state

        # Defines but does not automatically start the UI process.
        self._ui_process = Process(target=self._run_ui_process, daemon=True)
        self._started = False

    def __del__(self) -> None:
        """Ensures all class resources are released before the instance is destroyed.

        This is a fallback method, using shutdown() directly is the preferred way of releasing resources.
        """
        self.shutdown()

    def start(self) -> None:
        """Starts the remote UI process."""
        # Prevents starting an already started instance
        if self._started:
            return

        self._ui_process.start()
        self._started = True

    def shutdown(self) -> None:
        """Shuts down the UI and releases all SharedMemoryArray resources.

        This method should be called at the end of runtime to properly release all resources and terminate the
        remote UI process.
        """
        # Prevents shutting down an already terminated instance
        if not self._started:
            return

        # If the UI process is still alive, shuts it down
        if self._ui_process.is_alive():
            self._data_array.write_data(index=0, data=np.int32(1))  # Sends the termination signal to the remote process
            self._ui_process.terminate()
            self._ui_process.join(timeout=2.0)  # Waits for at most 2 seconds to terminate the process gracefully

        # Destroys the SharedMemoryArray
        self._data_array.disconnect()
        self._data_array.destroy()

        # Toggles the flag
        self._started = False

    def _run_ui_process(self) -> None:
        """The main function that runs in the parallel process to display and manage the Qt6 UI.

        This runs Qt6 in the main thread of the separate process, which is perfectly valid.
        """
        # Connects to the shared memory array from the remote process
        self._data_array.connect()

        # Create and run the Qt6 application in this process's main thread
        try:
            # Creates the QT5 GUI application
            app = QApplication(sys.argv)
            app.setApplicationName("Mesoscope-VR Control Panel")
            app.setOrganizationName("SunLab")

            # Sets Qt6 application-wide style
            app.setStyle("Fusion")  # Modern flat style available in Qt6

            # Creates the main application window
            window = _ControlUIWindow(self._data_array)
            window.show()

            # Runs the app
            app.exec()

        # Terminates with an exception which will be propagated to the main process
        except Exception as e:
            message = f"Unable to initialize the QT5 GUI application. Encountered the following error {e}."
            console.error(message=message, error=RuntimeError)

        # Ensures proper UI shutdown when runtime encounters errors
        finally:
            self._data_array.disconnect()

    def set_pause_state(self, paused: bool) -> None:
        """Sets the runtime pause state from outside the UI.

        This method is used to synchronize the remote GUI with the main runtime process if the runtime process enters
        the paused state. Typically, this happens when a major external component, such as the Mesoscope or Unity,
        unexpectedly terminates its runtime.

        Args:
            paused: Determines the externally assigned GUI pause state.
        """
        self._data_array.write_data(index=5, data=np.int32(1 if paused else 0))

    def set_guidance_state(self, enabled: bool) -> None:
        """Sets the guidance state from outside the UI.

        This method is used to synchronize the remote GUI with the main runtime process when the lick guidance state
        needs to be controlled programmatically.

        Args:
            enabled: Determines the externally assigned GUI guidance state.
        """
        self._data_array.write_data(index=9, data=np.int32(1 if enabled else 0))

    @property
    def exit_signal(self) -> bool:
        """Returns True if the user has requested the runtime to gracefully abort.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
        exit_flag = bool(self._data_array.read_data(index=1, convert_output=True))
        self._data_array.write_data(index=1, data=np.int32(0))
        return exit_flag

    @property
    def reward_signal(self) -> bool:
        """Returns True if the user has requested the system to deliver a water reward.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
        reward_flag = bool(self._data_array.read_data(index=2, convert_output=True))
        self._data_array.write_data(index=2, data=np.int32(0))
        return reward_flag

    @property
    def speed_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the running speed threshold."""
        return int(self._data_array.read_data(index=3, convert_output=True))

    @property
    def duration_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the running epoch duration threshold."""
        return int(self._data_array.read_data(index=4, convert_output=True))

    @property
    def pause_runtime(self) -> bool:
        """Returns True if the user has requested the acquisition system to pause the current runtime."""
        return bool(self._data_array.read_data(index=5, convert_output=True))

    @property
    def open_valve(self) -> bool:
        """Returns True if the user has requested the acquisition system to permanently open the water delivery
        valve.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
        open_flag = bool(self._data_array.read_data(index=6, convert_output=True))
        self._data_array.write_data(index=6, data=np.int32(0))
        return open_flag

    @property
    def close_valve(self) -> bool:
        """Returns True if the user has requested the acquisition system to permanently close the water delivery
        valve.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
        close_flag = bool(self._data_array.read_data(index=7, convert_output=True))
        self._data_array.write_data(index=7, data=np.int32(0))
        return close_flag

    @property
    def reward_volume(self) -> int:
        """Returns the current user-defined water reward volume value."""
        return int(self._data_array.read_data(index=8, convert_output=True))

    @property
    def enable_guidance(self) -> bool:
        """Returns True if the user has enabled lick guidance mode."""
        return bool(self._data_array.read_data(index=9, convert_output=True))

    @property
    def show_reward(self) -> bool:
        """Returns True if the reward zone collision boundary should be shown/displayed to the animal."""
        return bool(self._data_array.read_data(index=10, convert_output=True))


class _ControlUIWindow(QMainWindow):
    """Generates, renders, and maintains the main Mesoscope-VR acquisition system Graphical User Interface Qt6
    application window.

    This class binds the Qt6 GUI elements and statically defines the GUI element layout used by the main interface
    window application. The interface enables sl-experiment users to control certain runtime parameters in real time via
    an interactive GUI.

    Attributes:
        _data_array: A reference to the shared memory array used for communication between the main runtime thread
            and the Qt6 GUI.
        _is_paused: A flag indicating whether the runtime is paused or not.
        _speed_modifier: The current user-defined modifier to apply to the running speed threshold.
        _duration_modifier: The current user-defined modifier to apply to the running epoch duration threshold.
        _guidance_enabled: A flag indicating whether lick guidance mode is enabled or not.
        _show_reward: A flag indicating whether the reward zone collision boundary should be shown/displayed to the
            animal.
    """

    def __init__(self, data_array: SharedMemoryArray):
        super().__init__()  # Initializes the main window superclass

        # Defines internal attributes.
        self._data_array: SharedMemoryArray = data_array
        self._is_paused: bool = True
        self._speed_modifier: int = 0
        self._duration_modifier: int = 0
        self._guidance_enabled: bool = False
        self._show_reward: bool = True

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
        """Creates and arranges all UI elements optimized for Qt6 with proper scaling."""
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

        # Configures the buttons to expand when UI is resized, but use a fixed height of 35 points
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

        # Configures the buttons to expand when UI is resized, but use a fixed height of 35 points
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
        self.speed_spinbox.setValue(self._speed_modifier)  # Default value
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
        self.duration_spinbox.setValue(self._duration_modifier)  # Default value
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
        """Applies optimized styling to all UI elements managed by this class.

        This configured the UI to display properly, assuming the UI window uses the default resolution.
        """
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
        """Sets up a QTimer to monitor the runtime termination status.

        This monitors the value stored under index 0 of the communication SharedMemoryArray and, if the value becomes 1,
        triggers the GUI termination sequence.
        """
        self.monitor_timer = QTimer(self)
        # noinspection PyUnresolvedReferences
        self.monitor_timer.timeout.connect(self._check_external_state)
        self.monitor_timer.start(100)  # Checks every 100 ms

    def _check_external_state(self) -> None:
        """Checks the state of externally addressable SharedMemoryArray values and acts on received state updates.

        This method monitors certain values of the communication array to receive messages from the main runtime
        process. Primarily, this functionality is used to gracefully terminate the GUI from the main runtime process.
        """
        # noinspection PyBroadException
        try:
            # If the termination flag has been set to 1, terminates the GUI process
            if self._data_array.read_data(index=0, convert_output=True) == 1:
                self.close()

            # Checks for external pause state changes and, if necessary, updates the GUI to reflect the current
            # runtime state (running or paused).
            external_pause_state = bool(self._data_array.read_data(index=5, convert_output=True))
            if external_pause_state != self._is_paused:
                # External pause state changed, update UI accordingly
                self._is_paused = external_pause_state
                self._update_pause_ui()

            # Checks for external guidance state changes and, if necessary, updates the GUI to reflect the current
            # guidance state (enabled or disabled).
            external_guidance_state = bool(self._data_array.read_data(index=9, convert_output=True))
            if external_guidance_state != self._guidance_enabled:
                # External guidance state changed, update UI accordingly
                self._guidance_enabled = external_guidance_state
                self._update_guidance_ui()
        except:
            self.close()

    def closeEvent(self, event: QCloseEvent | None) -> None:
        """Handles GUI window close events.

        This function is called when the user manually closes the GUI window. This is treated as the request to
        terminate the ongoing runtime.

        Notes:
            Do not call this function manually! It is designed to be used by Qt GUI manager only.

        Args:
            event: The Qt-generated window shutdown event object.
        """
        # Sends a runtime termination signal via the SharedMemoryArray before accepting the close event.
        # noinspection PyBroadException
        try:
            self._data_array.write_data(index=0, data=np.int32(1))
        except:
            pass
        if event is not None:
            event.accept()

    def _exit_runtime(self) -> None:
        """Signals the runtime to gracefully terminate."""
        previous_status = self.runtime_status_label.text()
        style = self.runtime_status_label.styleSheet()
        self._data_array.write_data(index=1, data=np.int32(1))
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
        """Triggers the Mesoscope-VR system to deliver a single water reward to the animal.

        The size of the reward is addressable (configurable) via the reward volume box under the Valve control buttons.
        """
        # Sends the reward command via the SharedMemoryArray and temporarily sets the statsu to indicate that the
        # reward is sent.
        self._data_array.write_data(index=2, data=np.int32(1))
        self.valve_status_label.setText("Reward: 🟢 Sent")
        self.valve_status_label.setStyleSheet("QLabel { color: #3498db; font-weight: bold; }")

        # Resets the status to 'closed' after 1 second using the Qt6 single shot timer. This is realistically the
        # longest time the system would take to start and finish delivering the reward
        QTimer.singleShot(2000, lambda: self.valve_status_label.setText("Valve: 🔒 Closed"))
        QTimer.singleShot(
            2000, lambda: self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")
        )

    def _open_valve(self) -> None:
        """Permanently opens the water delivery valve."""
        self._data_array.write_data(index=6, data=np.int32(1))
        self.valve_status_label.setText("Valve: 🔓 Opened")
        self.valve_status_label.setStyleSheet("QLabel { color: #27ae60; font-weight: bold; }")

    def _close_valve(self) -> None:
        """Permanently closes the water delivery valve."""
        self._data_array.write_data(index=7, data=np.int32(1))
        self.valve_status_label.setText("Valve: 🔒 Closed")
        self.valve_status_label.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")

    def _toggle_pause(self) -> None:
        """Toggles the runtime between paused and unpaused (active) states."""
        self._is_paused = not self._is_paused
        self._data_array.write_data(index=5, data=np.int32(1 if self._is_paused else 0))
        self._update_pause_ui()

    def _update_reward_volume(self) -> None:
        """Updates the reward volume in the data array in response to the user modifying the GUI field value."""
        volume = int(self.volume_spinbox.value())
        self._data_array.write_data(index=8, data=np.int32(volume))

    def _update_speed_modifier(self) -> None:
        """Updates the speed modifier in the data array in response to the user modifying the GUI field value."""
        self._speed_modifier = int(self.speed_spinbox.value())
        self._data_array.write_data(index=3, data=np.int32(self._speed_modifier))

    def _update_duration_modifier(self) -> None:
        """Updates the duration modifier in the data array in response to the user modifying the GUI field value."""
        self._duration_modifier = int(self.duration_spinbox.value())
        self._data_array.write_data(index=4, data=np.int32(self._duration_modifier))

    def _update_guidance_ui(self) -> None:
        """Updates the guidance UI elements based on the current _guidance_enabled state."""
        if self._guidance_enabled:
            self.guidance_btn.setText("🚫 Disable Guidance")
            self.guidance_btn.setObjectName("guidanceDisableButton")
        else:
            self.guidance_btn.setText("🎯 Enable Guidance")
            self.guidance_btn.setObjectName("guidanceButton")

        # Refresh styles after object name change
        self.guidance_btn.style().unpolish(self.guidance_btn)  # type: ignore
        self.guidance_btn.style().polish(self.guidance_btn)  # type: ignore
        self.guidance_btn.update()  # Forces update to apply new styles

    def _toggle_guidance(self) -> None:
        """Toggles guidance mode between enabled and disabled states."""
        self._guidance_enabled = not self._guidance_enabled
        self._data_array.write_data(index=9, data=np.int32(1 if self._guidance_enabled else 0))
        self._update_guidance_ui()

    def _update_pause_ui(self) -> None:
        """Updates the pause UI elements based on the current _is_paused state."""
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
        self.pause_btn.style().unpolish(self.pause_btn)  # type: ignore
        self.pause_btn.style().polish(self.pause_btn)  # type: ignore
        self.pause_btn.update()  # Forces update to apply new styles

    def _toggle_reward_visibility(self) -> None:
        """Toggles reward collision boundary visibility between shown and hidden states."""
        self._show_reward = not self._show_reward
        if self._show_reward:
            self._data_array.write_data(index=10, data=np.int32(1))
            self.reward_visibility_btn.setText("🙈 Hide Reward")
            self.reward_visibility_btn.setObjectName("hideRewardButton")
        else:
            self._data_array.write_data(index=10, data=np.int32(0))
            self.reward_visibility_btn.setText("👁️ Show Reward")
            self.reward_visibility_btn.setObjectName("showRewardButton")

        # Refresh styles after object name change
        self.reward_visibility_btn.style().unpolish(self.reward_visibility_btn)  # type: ignore
        self.reward_visibility_btn.style().polish(self.reward_visibility_btn)  # type: ignore
        self.reward_visibility_btn.update()  # Forces update to apply new styles


class CachedMotifDecomposer:
    """A helper class to cache the flattened Trial cue sequence motif data between multiple motif decomposition
    runtimes.

    Trial motifs are used during experiment runtimes to decompose a long sequence of VR wall cues into trials. In turn,
    this is used to track the animal's performance during runtime (for each trial) and, if necessary, enable or disable
    lick guidance. Since each experiment can use one or more trial motifs (cue sequences), this decomposition has to be
    performed at runtime for each experiment. To optimize runtime performance, this class prepares and stores the
    necessary dat to support numba-accelerated motif decomposition at runtime, especially in (rare) cases where it has
    to be performed multiple times due to Unity crashing.

    Attributes:
        _cached_motifs: Stores the original trial motifs used for decomposition.
        _cached_flat_data: Stores flattened motif data structure, optimized for numba-accelerated computations.
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
            trial_motifs: A list of trial motifs (wall cue sequences) in the format of numpy arrays.
            trial_distances: A list of trial distances in centimeters.

        Returns:
            A tuple containing five elements. The first element is a flattened array of all motifs. The second
            element is an array that stores the starting indices of each motif in the flat array. The third element is
            an array that stores the length of each motif. The fourth element is an array that stores the original
            indices of motifs before sorting. The fifth element is an array of trial distances in centimeters.
        """
        # Checks if the class already contains cached data for the input motifs. In this case, returns the cached data.
        if self._cached_motifs is not None and len(self._cached_motifs) == len(trial_motifs):
            # Carries out deep comparison of motif arrays
            all_equal = all(
                np.array_equal(cached, current) for cached, current in zip(self._cached_motifs, trial_motifs)
            )
            if all_equal and self._cached_flat_data is not None and self._cached_distances is not None:
                return self._cached_flat_data + (self._cached_distances,)

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

        # noinspection PyTypeChecker
        return self._cached_flat_data + (distances_array,)
