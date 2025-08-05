from pathlib import Path
from dataclasses import field, dataclass

import numpy as np
from _typeshed import Incomplete
from PyQt6.QtGui import QCloseEvent
from numpy.typing import NDArray as NDArray
from PyQt6.QtWidgets import QMainWindow
from sl_shared_assets import SessionData, MesoscopeSystemConfiguration
from ataraxis_data_structures import SharedMemoryArray

def get_system_configuration() -> MesoscopeSystemConfiguration:
    """Verifies that the current data acquisition system is the Mesoscope-VR and returns its configuration data.

    Raises:
        ValueError: If the local data acquisition system is not a Mesoscope-VR system.
    """
@dataclass()
class _VRPCPersistentData:
    """Stores the paths to the directories and files that make up the 'persistent_data' directory on the VRPC.

    VRPC persistent data directory is used to preserve configuration data, such as the positions of Zaber motors and
    Meososcope objective, so that they can be reused across sessions of the same animals. The data in this directory
    is read at the beginning of each session and replaced at the end of each session.
    """

    session_type: str
    persistent_data_path: Path
    zaber_positions_path: Path = field(default_factory=Path, init=False)
    mesoscope_positions_path: Path = field(default_factory=Path, init=False)
    session_descriptor_path: Path = field(default_factory=Path, init=False)
    window_screenshot_path: Path = field(default_factory=Path, init=False)
    def __post_init__(self) -> None: ...

@dataclass()
class _ScanImagePCData:
    """Stores the paths to the directories and files that make up the 'meso_data' directory on the ScanImagePC.

    During runtime, the ScanImagePC should organize all collected data under this root directory. During preprocessing,
    the VRPC uses SMB to access the data in this directory and merge it into the 'raw_data' session directory. The root
    ScanImagePC directory also includes the persistent_data directories for all animals and projects whose data is
    acquired via the Mesoscope-VR system.
    """

    session_name: str
    meso_data_path: Path
    persistent_data_path: Path
    mesoscope_data_path: Path = field(default_factory=Path, init=False)
    session_specific_path: Path = field(default_factory=Path, init=False)
    ubiquitin_path: Path = field(default_factory=Path, init=False)
    motion_estimator_path: Path = field(default_factory=Path, init=False)
    roi_path: Path = field(default_factory=Path, init=False)
    kinase_path: Path = field(default_factory=Path, init=False)
    phosphatase_path: Path = field(default_factory=Path, init=False)
    def __post_init__(self) -> None: ...

@dataclass()
class _VRPCDestinations:
    """Stores the paths to the VRPC filesystem-mounted directories of the Synology NAS and BioHPC server.

    The paths from this section are primarily used to transfer preprocessed data to the long-term storage destinations.
    """

    nas_raw_data_path: Path
    server_raw_data_path: Path
    server_processed_data_path: Path
    telomere_path: Path = field(default_factory=Path, init=False)
    def __post_init__(self) -> None: ...

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

    vrpc_persistent_data: Incomplete
    scanimagepc_data: Incomplete
    destinations: Incomplete
    def __init__(self, session_data: SessionData) -> None: ...

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

    _data_array: Incomplete
    _ui_process: Incomplete
    _started: bool
    def __init__(self) -> None: ...
    def __del__(self) -> None:
        """Ensures all class resources are released before the instance is destroyed.

        This is a fallback method, using shutdown() directly is the preferred way of releasing resources.
        """
    def start(self) -> None:
        """Starts the remote UI process."""
    def shutdown(self) -> None:
        """Shuts down the UI and releases all SharedMemoryArray resources.

        This method should be called at the end of runtime to properly release all resources and terminate the
        remote UI process.
        """
    def _run_ui_process(self) -> None:
        """The main function that runs in the parallel process to display and manage the Qt6 UI.

        This runs Qt6 in the main thread of the separate process, which is perfectly valid.
        """
    def set_pause_state(self, paused: bool) -> None:
        """Sets the runtime pause state from outside the UI.

        This method is used to synchronize the remote GUI with the main runtime process if the runtime process enters
        the paused state. Typically, this happens when a major external component, such as the Mesoscope or Unity,
        unexpectedly terminates its runtime.

        Args:
            paused: Determines the externally assigned GUI pause state.
        """
    def set_guidance_state(self, enabled: bool) -> None:
        """Sets the guidance state from outside the UI.

        This method is used to synchronize the remote GUI with the main runtime process when the lick guidance state
        needs to be controlled programmatically.

        Args:
            enabled: Determines the externally assigned GUI guidance state.
        """
    @property
    def exit_signal(self) -> bool:
        """Returns True if the user has requested the runtime to gracefully abort.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
    @property
    def reward_signal(self) -> bool:
        """Returns True if the user has requested the system to deliver a water reward.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
    @property
    def speed_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the running speed threshold."""
    @property
    def duration_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the running epoch duration threshold."""
    @property
    def pause_runtime(self) -> bool:
        """Returns True if the user has requested the acquisition system to pause the current runtime."""
    @property
    def open_valve(self) -> bool:
        """Returns True if the user has requested the acquisition system to permanently open the water delivery
        valve.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
    @property
    def close_valve(self) -> bool:
        """Returns True if the user has requested the acquisition system to permanently close the water delivery
        valve.

        Notes:
            Each time this property is accessed, the flag is reset to 0.
        """
    @property
    def reward_volume(self) -> int:
        """Returns the current user-defined water reward volume value."""
    @property
    def enable_guidance(self) -> bool:
        """Returns True if the user has enabled lick guidance mode."""
    @property
    def show_reward(self) -> bool:
        """Returns True if the reward zone collision boundary should be shown/displayed to the animal."""

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

    _data_array: SharedMemoryArray
    _is_paused: bool
    _speed_modifier: int
    _duration_modifier: int
    _guidance_enabled: bool
    _show_reward: bool
    def __init__(self, data_array: SharedMemoryArray) -> None: ...
    exit_btn: Incomplete
    pause_btn: Incomplete
    guidance_btn: Incomplete
    reward_visibility_btn: Incomplete
    runtime_status_label: Incomplete
    valve_open_btn: Incomplete
    valve_close_btn: Incomplete
    reward_btn: Incomplete
    volume_spinbox: Incomplete
    valve_status_label: Incomplete
    speed_spinbox: Incomplete
    duration_spinbox: Incomplete
    def _setup_ui(self) -> None:
        """Creates and arranges all UI elements optimized for Qt6 with proper scaling."""
    def _apply_qt6_styles(self) -> None:
        """Applies optimized styling to all UI elements managed by this class.

        This configured the UI to display properly, assuming the UI window uses the default resolution.
        """
    monitor_timer: Incomplete
    def _setup_monitoring(self) -> None:
        """Sets up a QTimer to monitor the runtime termination status.

        This monitors the value stored under index 0 of the communication SharedMemoryArray and, if the value becomes 1,
        triggers the GUI termination sequence.
        """
    def _check_external_state(self) -> None:
        """Checks the state of externally addressable SharedMemoryArray values and acts on received state updates.

        This method monitors certain values of the communication array to receive messages from the main runtime
        process. Primarily, this functionality is used to gracefully terminate the GUI from the main runtime process.
        """
    def closeEvent(self, event: QCloseEvent | None) -> None:
        """Handles GUI window close events.

        This function is called when the user manually closes the GUI window. This is treated as the request to
        terminate the ongoing runtime.

        Notes:
            Do not call this function manually! It is designed to be used by Qt GUI manager only.

        Args:
            event: The Qt-generated window shutdown event object.
        """
    def _exit_runtime(self) -> None:
        """Signals the runtime to gracefully terminate."""
    def _deliver_reward(self) -> None:
        """Triggers the Mesoscope-VR system to deliver a single water reward to the animal.

        The size of the reward is addressable (configurable) via the reward volume box under the Valve control buttons.
        """
    def _open_valve(self) -> None:
        """Permanently opens the water delivery valve."""
    def _close_valve(self) -> None:
        """Permanently closes the water delivery valve."""
    def _toggle_pause(self) -> None:
        """Toggles the runtime between paused and unpaused (active) states."""
    def _update_reward_volume(self) -> None:
        """Updates the reward volume in the data array in response to the user modifying the GUI field value."""
    def _update_speed_modifier(self) -> None:
        """Updates the speed modifier in the data array in response to the user modifying the GUI field value."""
    def _update_duration_modifier(self) -> None:
        """Updates the duration modifier in the data array in response to the user modifying the GUI field value."""
    def _update_guidance_ui(self) -> None:
        """Updates the guidance UI elements based on the current _guidance_enabled state."""
    def _toggle_guidance(self) -> None:
        """Toggles guidance mode between enabled and disabled states."""
    def _update_pause_ui(self) -> None:
        """Updates the pause UI elements based on the current _is_paused state."""
    def _toggle_reward_visibility(self) -> None:
        """Toggles reward collision boundary visibility between shown and hidden states."""

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

    _cached_motifs: list[NDArray[np.uint8]] | None
    _cached_flat_data: tuple[NDArray[np.uint8], NDArray[np.int32], NDArray[np.int32], NDArray[np.int32]] | None
    _cached_distances: NDArray[np.float32] | None
    def __init__(self) -> None: ...
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
