import numpy as np
from _typeshed import Incomplete
from numpy.typing import NDArray as NDArray
from ataraxis_time import PrecisionTimer
from sl_shared_assets import (
    SessionData,
    RunTrainingDescriptor,
    LickTrainingDescriptor,
    WindowCheckingDescriptor,
    MesoscopeExperimentDescriptor,
    MesoscopeExperimentConfiguration,
)
from ataraxis_data_structures import DataLogger
from ataraxis_communication_interface import MQTTCommunication

from .tools import (
    MesoscopeData as MesoscopeData,
    RuntimeControlUI as RuntimeControlUI,
    CachedMotifDecomposer as CachedMotifDecomposer,
    get_system_configuration as get_system_configuration,
)
from .visualizers import BehaviorVisualizer as BehaviorVisualizer
from .binding_classes import (
    ZaberMotors as ZaberMotors,
    VideoSystems as VideoSystems,
    MicroControllerInterfaces as MicroControllerInterfaces,
)
from ..shared_components import (
    WaterSheet as WaterSheet,
    SurgerySheet as SurgerySheet,
    BreakInterface as BreakInterface,
    ValveInterface as ValveInterface,
    get_version_data as get_version_data,
    get_animal_project as get_animal_project,
    get_project_experiments as get_project_experiments,
)
from .data_preprocessing import (
    purge_failed_session as purge_failed_session,
    preprocess_session_data as preprocess_session_data,
    rename_mesoscope_directory as rename_mesoscope_directory,
)

def _generate_mesoscope_position_snapshot(session_data: SessionData, mesoscope_data: MesoscopeData) -> None:
    """Generates a precursor mesoscope_positions.yaml file and optionally forces the user to update it to reflect
    the current Mesoscope objective position coordinates.

    This utility method is used as part of the experiment and window checking runtimes shutdown sequence to generate a
    snapshot of Mesoscope objective positions that will be reused during the next session to restore the imaging field.

    Args:
        session_data: The SessionData instance for the runtime for which the snapshot is generated.
        mesoscope_data: The MesoscopeData instance for the runtime for which the snapshot is generated.
    """

def _generate_zaber_snapshot(
    session_data: SessionData, mesoscope_data: MesoscopeData, zaber_motors: ZaberMotors
) -> None:
    """Creates a snapshot of current Zaber motor positions and saves them to the session raw_data folder and the
    persistent folder of the animal that participates in the runtime.

    Args:
        zaber_motors: The ZaberMotors instance for the runtime for which the snapshot is generated.
        session_data: The SessionData instance for the runtime for which the snapshot is generated.
        mesoscope_data: The MesoscopeData instance for the runtime for which the snapshot is generated.
    """

def _setup_zaber_motors(zaber_motors: ZaberMotors) -> None:
    """If necessary, carries out the Zaber motor setup and positioning sequence.

    This method is used as part of the startup procedure for most runtimes to prepare the Zaber motors for the specific
    animal that participates in the runtime.

    Args:
        zaber_motors: The ZaberMotors instance that manages the Zaber motors used during runtime.
    """

def _reset_zaber_motors(zaber_motors: ZaberMotors) -> None:
    """Optionally resets Zaber motors back to the hardware-defined parking positions.

    This method is called as part of the shutdown procedure for most runtimes to achieve two major goals. First, it
    facilitates removing the animal from the Mesoscope enclosure by retracting the lick-port away from its head. Second,
    it positions Zaber motors in a way that ensures that the motors can be safely homed after potential power cycling.

    Args:
        zaber_motors: The ZaberMotors instance that manages the Zaber motors used during runtime.
    """

def _setup_mesoscope(session_data: SessionData, mesoscope_data: MesoscopeData) -> None:
    """Prompts the user to carry out steps to prepare the mesoscope for acquiring brain activity data or checking the
    quality of the cranial window.

    This method is used as part of the start() method execution for experiment runtimes to ensure the mesoscope is ready
    for data acquisition. It is also used by the window_checking runtime to guide the user through the process of
    generating the required data to potentially support future experiments. It guides the user through all mesoscope
    preparation steps and, at the end of runtime, ensures the mesoscope is ready for acquisition.

    Args:
        session_data: The SessionData instance for the runtime for which to set up the mesoscope.
        mesoscope_data: The MesoscopeData instance for the runtime for which to set up the mesoscope.
    """

def _verify_descriptor_update(
    descriptor: MesoscopeExperimentDescriptor
    | LickTrainingDescriptor
    | RunTrainingDescriptor
    | WindowCheckingDescriptor,
    session_data: SessionData,
    mesoscope_data: MesoscopeData,
) -> None:
    """Caches the input descriptor instance to the target session's raw_data folder and forces the user to update the
    data stored inside the cached descriptor file with runtime notes.

    This utility method is used to ensure that the user adds their runtime notes to the runtime descriptor file. It is
    shared by all session (runtime) types.

    Args:
        descriptor: The session_descriptor.yaml-convertible class instance to cache to the target session's
            raw_data folder.
        session_data: The SessionData instance for the runtime for which to generate the descriptor .yaml file.
        mesoscope_data: The MesoscopeData instance for the runtime for which to generate the descriptor .yaml file.
    """

class _MesoscopeVRSystem:
    """The base class for all Mesoscope-VR system runtimes.

    This class provides methods for conducting training and experiment sessions using the Mesoscope-VR system.
    It abstracts most low-level interactions with the mesoscope (2P-RAM) and Virtual Reality (VR) system components by
    providing a high-level API and a cyclic method that synchronizes the state of all Mesoscope-VR components during
    runtime.

    Notes:
        Calling this initializer only instantiates a minimal subset of all Mesoscope-VR assets. Use the start() method
        before issuing other commands to properly initialize all required runtime assets and remote processes.

        This class statically reserves the id code '1' to label its log entries. Make sure no other Ataraxis class,
        such as MicroControllerInterface or VideoSystem, uses this id code.

    Args:
        session_data: An initialized SessionData instance used to control the flow of data during acquisition and
            preprocessing. Each instance is initialized for the specific project, animal, and session combination for
            which the data is acquired.
        session_descriptor: A partially initialized LickTrainingDescriptor, RunTrainingDescriptor, or
            MesoscopeExperimentDescriptor instance. This instance is used to store session-specific information in a
            human-readable format.
        experiment_configuration: Only for experiment sessions. An initialized MesoscopeExperimentConfiguration instance
            that specifies experiment configuration and experiment state sequence. Keep this set to None for behavior
            training sessions.

    Attributes:
        _state_map: Maps the integer state-codes used to represent VR system states to human-readable string-names.
        _unity_termination_topic: Stores the MQTT topic used by Unity task environment to announce when it terminates
            the active game state (stops 'playing' the task environment).
        _unity_startup_topic: Stores the MQTT topic used by Unity task environment to announce when it starts
            the active game state (starts 'playing' the task environment).
        _cue_sequence_topic: Stores the MQTT topic used by Unity task environment to respond to the request of the VR
            wall cue sequence sent to the '_cue_sequence_request_topic'.
        _cue_sequence_request_topic: Stores the MQTT topic used to request the Unity virtual task to send the sequence
            of wall cues used during runtime. The data is sent to the topic specified by '_cue_sequence_topic'.
        _disable_guidance_topic: Stores the MQTT topic used to switch the virtual task into unguided mode (animal must
            lick to receive water).
        _enable_guidance_topic: Stores the MQTT topic used to switch the virtual task into guided mode (the water
            dispenses automatically when the animal enters the reward zone).
        _show_reward_zone_boundary_topic: Stores the MQTT topic used to show the reward zone collision boundary to
            the animal. The collision boundary is the typically hidden virtual wall the animal must collide with to
            trigger automated (guided) water reward delivery.
        _hide_reward_zone_boundary_topic: Stores the MQTT topic used to hide the reward zone collision boundary from
            the animal.
        _system_state_code: Stores the log message ID code used to log changes to Mesoscope-VR system state.
        _runtime_state_code: Stores the log message ID code used to log changes to the runtime state.
        _guidance_state_code: Stores the log message ID code used to log changes to the lick guidance state.
        _show_reward_code: Stores the log message ID code used to log changes to reward zone collision wall visibility
            state.
        _distance_snapshot_code: Stores the log message ID code used to log cumulative distance traveled by the animal
            at the time when the system received an unexpected Unity termination message.
        _mesoscope_frame_delay: Stores the maximum number of milliseconds expected to pass between two consecutive
            mesoscope frame acquisition triggers. By default, this is configured assuming that the acquisition is
            adjusted to ~10 Hz.
        _speed_calculation_window: Determines the window size, in milliseconds, used to calculate the running speed
            of the animal.
        _source_id: Stores the unique identifier code for this class instance. The identifier is used to mark log
            entries made by this class instance and has to be unique across all sources that log data at the same time,
            such as MicroControllerInterfaces and VideoSystems.
        _started: Tracks whether runtime assets have been initialized (started).
        _terminated: Tracks whether the user has terminated the runtime.
        _paused: Tracks whether the user has paused the runtime.
        _mesoscope_started: ZTracks whether the Mesoscope-VR system has started Mesoscope frame acquisition as part of
            this runtime.
        descriptor: Stores the session descriptor instance of the managed session.
        _experiment_configuration: Stores the MesoscopeExperimentConfiguration instance of the managed session, if the
            session is of the 'mesoscope experiment' type.
        _session_data: Stores the SessionData instance of the managed session.
        _mesoscope_data: Stores the MesoscopeData instance of the managed session.
        _system_state: Stores the current state-code of the Mesoscope-VR system.
        _runtime_state: Stores the current state-code of the runtime (training / experiment stage).
        _timestamp_timer: A PrecisionTimer instance used to timestamp log entries generated by the class instance. This
            timer is also co-opted to track the time spent in the paused state when the runtime is paused.
        _position: Stores the current absolute position of the animal relative to the starts of the Virtual Reality
            track, in Unity units.
        _distance: Stores the total cumulative distance, in centimeters, traveled by the animal since runtime onset.
        _lick_count: Stores the total number of licks performed by the animal since runtime onset.
        _cue_sequence: Stores the VR track wall cue sequence used by the currently active Unity task environment.
        _unconsumed_reward_count: Stores the number of rewards delivered to the animal without the animal consuming
            them. This number resets each time the animal licks the water delivery tube.
        _enable_guidance: Determines whether the runtime is currently executed in the guided mode.
        _show_reward_zone_boundary: Determines whether the reward zone collision wall is currently visible.
        _pause_start_time: Stores the absolute time of the last paused state onset, in microseconds since UTC onset.
        paused_time: Stores the total time, in seconds, the runtime spent in the paused (idle) state.
        _delivered_water_volume: Stores the total volume of water dispensed by the water delivery valve during runtime
            (outside the paused / idle state).
        _unity_terminated: Determines whether the runtime has detected that the Unity game engine has unexpectedly
            terminated its runtime (sent a system shutdown message).
        _mesoscope_frame_count: Tracks the number of frames acquired by the Mesoscope since the last acquisition onset.
        _mesoscope_terminated: Determines whether the runtime has detected that the Mesoscope has unexpectedly
            terminated its runtime (stopped sending frame pulses and responding to recovery triggers).
        _running_speed: Stores the running speed of the animal, in centimeters per second, computed over the preceding
            50 milliseconds of runtime.
        _speed_timer: Stores the PrecisionTimer instance used to computer the running speed of the animal in
            50-millisecond intervals.
        _guided_trials: Stores the remaining number of trials which should be executed in the guided mode.
        _failed_trials: Stores the number of sequential trials for which the animal did not receive
            a reward. If the animal performs a rewarded trial, this sequence counter is reset to 0.
        _failed_trial_threshold: Stores the maximum number of trials the animal can fail (not receive reward) in a row
            for the system to engage lick guidance for the next _recovery_trials number of trials.
        _recovery_trials: Stores the number of trials for which the system should enable lick guidance if the animal
            fails the previous _failed_trial_threshold trials in a row.
        _trial_rewarded: Tracks whether the currently executed trial has been rewarded.
        _trial_distances: A NumPy array that stores the total cumulative distance, in centimeters, the animals would
            travel at the end of each trial. The order of items in the array matches the order of trials experienced by
            the animal.
        _trial_rewards: A tuple that stores the reward size (volume) to be received by the animal for successfully
            completing trials during runtime, in microliters. The order of items in the tuple matches the order of
            trials experienced by the animal.
        _completed_trials: Stores the total number of trials completed by the animal since the last cue sequence
            reset.
        _paused_water_volume: Tracks the total volume of water, in milliliters, dispensed by the water delivery valve
            during the paused state.
        _logger: Stores the DataLogger instance that collects behavior log data from all sources.
        _microcontrollers: Stores the MicroControllerInterfaces instance that interfaces with all MicroController
            devices used during runtime.
        _cameras: Stores the VideoSystems instance that interfaces with video systems (cameras) used during
            runtime.
        _zaber_motors: Stores the ZaberMotors class instance that interfaces with HeadBar, LickPort, and Wheel motors.
        _ui: Stores the RuntimeControlUI instance used during runtime to allow the user to interface with the
            Mesoscope-VR system via QT6 GUI.
        _visualizer: Stores the BehaviorVisualizer instance used during runtime to visualize certain animal behavior
            data. If the managed runtime does not use a visualizer, this attribute is set to None.
        _mesoscope_timer: Stores the PrecisionTimer instance used to track the delay between receiving consecutive
            mesoscope frame acquisition pulses. This is used to detect and rectify a rare case where mesoscope
            acquisition unexpectedly stops.
        _motif_decomposer: Stores the MotifDecomposer instance used during runtime to decompose long VR cue sequences
            into the sequence of trials and corresponding cumulative traveled distance associated with each trial.

    Raises:
        RuntimeError: If the host PC does not have enough logical CPU cores to support the runtime.
    """

    _state_map: dict[str, int]
    _unity_termination_topic: str
    _unity_startup_topic: str
    _cue_sequence_topic: str
    _cue_sequence_request_topic: str
    _disable_guidance_topic: str
    _enable_guidance_topic: str
    _show_reward_zone_boundary_topic: str
    _hide_reward_zone_boundary_topic: str
    _unity_scene_request_topic: str
    _unity_scene_topic: str
    _system_state_code: int
    _runtime_state_code: int
    _guidance_state_code: int
    _show_reward_code: int
    _distance_snapshot_code: int
    _mesoscope_frame_delay: int
    _speed_calculation_window: int
    _source_id: np.uint8
    _started: bool
    _terminated: bool
    _paused: bool
    _mesoscope_started: bool
    descriptor: MesoscopeExperimentDescriptor | LickTrainingDescriptor | RunTrainingDescriptor
    _experiment_configuration: MesoscopeExperimentConfiguration | None
    _session_data: SessionData
    _mesoscope_data: MesoscopeData
    _system_state: int
    _runtime_state: int
    _timestamp_timer: PrecisionTimer
    _position: np.float64
    _distance: np.float64
    _lick_count: np.uint64
    _cue_sequence: NDArray[np.uint8]
    _unconsumed_reward_count: int
    _enable_guidance: bool
    _show_reward_zone_boundary: bool
    _pause_start_time: int
    paused_time: int
    _delivered_water_volume: np.float64
    _unity_terminated: bool
    _mesoscope_frame_count: np.uint64
    _mesoscope_terminated: bool
    _running_speed: np.float64
    _speed_timer: Incomplete
    _guided_trials: int
    _failed_trials: int
    _failed_trial_threshold: int
    _recovery_trials: int
    _trial_rewarded: bool
    _trial_distances: NDArray[np.float64]
    _trial_rewards: tuple[float, ...]
    _completed_trials: int
    _paused_water_volume: np.float64
    _logger: DataLogger
    _microcontrollers: MicroControllerInterfaces
    _cameras: VideoSystems
    _zaber_motors: ZaberMotors
    _unity: MQTTCommunication | None
    _mesoscope_timer: PrecisionTimer | None
    _motif_decomposer: Incomplete
    _ui: RuntimeControlUI
    _visualizer: BehaviorVisualizer
    def __init__(
        self,
        session_data: SessionData,
        session_descriptor: MesoscopeExperimentDescriptor | LickTrainingDescriptor | RunTrainingDescriptor,
        experiment_configuration: MesoscopeExperimentConfiguration | None = None,
    ) -> None: ...
    def start(self) -> None:
        """Initializes and configures all internal and external assets used during the runtime and guides the user
        through all runtime preparation steps.

        This method establishes the communication with the microcontrollers, data logger cores, and video system
        processes. It also executes the runtime preparation sequence, which includes positioning all Zaber motors
        to support the runtime and generating data files that store runtime metadata. When starting a runtime that uses
        Unity game engine and / or Mesoscope, this method also guides the user through appropriate steps for setting
        up these external assets.

        Notes:
            As part of its runtime, this method attempts to set all Zaber motors to the optimal runtime position for the
            participating animal. Exercise caution and always monitor the system when it is running this method,
            as motor motion can damage the mesoscope or harm the animal. It is the responsibility of the user to ensure
            that the execution of all Zaber motor commands is safe.

            At the end of this method's successful runtime, the Mesoscope-VR system is necessarily ready to handle
            the runtime control over to the runtime logic function and / or Unity.
        """
    def stop(self) -> None:
        """Stops and terminates all Mesoscope-VR system components, external assets, and ends the runtime.

        This method releases the hardware resources used during runtime by various system components by triggering
        appropriate graceful shutdown procedures for all components. Then, it generates a set of files that store
        various runtime metadata. Finally, it calls the data preprocessing pipeline to efficiently package the data and
        safely transfer it to the long-term storage destinations.
        """
    def _checkpoint(self) -> None:
        """Instructs the user to verify the functioning of the water delivery valve and all other components before
        starting the runtime.

        This utility method is called as part of the start() method to allow the user to ensure that all critical system
        elements are ready for runtime. This method is designed to run briefly and is primarily intended for the user
        to test the valve before starting the runtime.
        """
    def _setup_zaber_motors(self) -> None:
        """If necessary, carries out the Zaber motor setup and positioning sequence.

        This method is used as part of the start() method execution for most runtimes to prepare the Zaber motors for
        the specific animal that participates in the runtime.
        """
    def _reset_zaber_motors(self) -> None:
        """Optionally resets Zaber motors back to the hardware-defined parking positions.

        This method is called as part of the stop() method runtime to achieve two major goals. First, it facilitates
        removing the animal from the Mesoscope enclosure by retracting the lick-port away from its head. Second, it
        positions Zaber motors in a way that ensures that the motors can be safely homed after potential power cycling.
        """
    def _generate_zaber_snapshot(self) -> None:
        """Creates a snapshot of current Zaber motor positions and saves them to the session raw_dat folder and the
        persistent folder of the animal that participates in the runtime."""
    def _setup_mesoscope(self) -> None:
        """Prompts the user to prepare the mesoscope for acquiring brain activity data.

        This method is used as part of the start() method execution for experiment runtimes to ensure the
        mesoscope is ready for data acquisition. It guides the user through all mesoscope preparation steps and, at
        the end of runtime, ensures the mesoscope is ready for acquisition.
        """
    def _start_mesoscope(self) -> None:
        """Generates the acquisition start marker file on the ScanImagePC and waits for the frame acquisition to begin.

        This method is used internally to start the mesoscope frame acquisition as part of the runtime startup
        process and to verify that the mesoscope is available and properly configured to acquire frames
        based on the input triggers.

        Notes:
            This method contains an infinite loop that allows retrying the failed mesoscope acquisition start. This
            prevents the runtime from aborting unless the user purposefully chooses the hard abort option.

        Raises:
            RuntimeError: If the mesoscope does not confirm frame acquisition within 2 seconds after the
                acquisition marker file is created, and the user chooses to abort the runtime.
        """
    def _stop_mesoscope(self) -> None:
        """Sends the frame acquisition stop TTL pulse to the mesoscope and waits for the frame acquisition to stop.

        This method is used internally to stop the mesoscope frame acquisition as part of the stop() method runtime.

        Notes:
            This method contains an infinite loop that waits for the mesoscope to stop generating frame acquisition
            triggers.
        """
    def _generate_mesoscope_position_snapshot(self) -> None:
        """Generates a precursor mesoscope_positions.yaml file and instructs the user to update it to reflect
        the current Mesoscope objective position coordinates.

        This utility method is used during the stop() method runtime to generate a snapshot of Mesoscope objective
        positions that will be reused during the next session to restore the imaging field.

        Notes:
            Since version 3.0.0, this data includes the laser power delivered to the sample and the z-axis position
            used for red dot alignment.
        """
    def _generate_hardware_state_snapshot(self) -> None:
        """Resolves and generates the snapshot of hardware configuration parameters used by the Mesoscope-VR system
        modules.

        This method determines which modules are used by the executed runtime (session) type and caches their
        configuration data into a HardwareStates object stored inside the session's raw_data folder.
        """
    def _generate_session_descriptor(self) -> None:
        """Updates the contents of the locally stored session descriptor file with runtime data and caches it to
         the session's raw_data directory.

        This utility method is used as part of the stop() method runtime to generate the session_descriptor.yaml file.
        Since this file combines both runtime-generated and user-generated data, this method also ensures that the
        user updates the descriptor file to include experimenter notes taken during runtime.
        """
    def _setup_unity(self) -> None:
        """Guides the user through verifying that Unity is configured to correctly display the task environment on the
        VR screens.

        This method forces each user to check that their virtual task properly displays on the VR screens to avoid
        issues with experiment runtimes that rely on delivering visual feedback to the animal. To do so, it generates
        an artificial motion signal and enables / disables the VR screens for the user to verify and, if necessary,
        tweak the screen allocation. As part of its runtime, the method ensures that the Unity task starts at least
        once.

        Raises:
            RuntimeError: If Unity does not send a start message within 10 minutes of this runtime starting, and
                the user chooses to abort the runtime.
        """
    def _get_cue_sequence(self) -> None:
        """Queries the sequence of virtual reality track wall cues for the current task from Unity.

        This method is used to both get the static VR task cue sequence and to verify that the Unity task is currently
        running. It is called as part of the start() method and to recover from unexpected Unity shutdowns that
        occur during runtime.

        Notes:
            This method contains an infinite loop that allows retrying failed connection attempts. This prevents the
            runtime from aborting unless the user purposefully chooses the hard abort option.

            Upon receiving the cue sequence data, the method caches the data into the private _cue_sequence class
            attribute. The attribute can be used to handle 'blackout teleportation' runtime events entirely through
            Python, bypassing the need for specialized Unity logic.

        Raises:
            RuntimeError: If the user chooses to abort the runtime when the method does not receive a response from
                Unity in 5 seconds.
        """
    def _verify_unity_task(self) -> None:
        """Queries the name of the playing scene for the current VR task from Unity.

        This method is used as part of the initial Unity setup sequence to ensure that Unity is set to display the
        correct VR task for the executed experiment runtime.

        Notes:
            This method contains an infinite loop that allows retrying failed connection attempts. This prevents the
            runtime from aborting unless the user purposefully chooses the hard abort option.

        Raises:
            RuntimeError: If the user chooses to abort the runtime when the method does not receive a response from
                Unity in 5 seconds.
            ValueError: If the Unity transmits a scene name that does not match the expected VR task name loaded from
                the experiment configuration file.
        """
    def _decompose_cue_sequence_into_trials(self) -> None:
        """Decomposes the Virtual Reality task wall cue sequence into a sequence of trials.

        Uses a greedy longest-match approach to identify trial motifs in the cue sequence and maps them to their trial
        distances and water reward sizes based on the experiment_configuration file data. This transformation allows
        the runtime control logic to keep track of the animal's performance and determine what rewards to deliver to the
        animal when it performs well.

        Raises:
            RuntimeError: If the method is not able to fully decompose the experiment cue sequence into a set of trial
                lengths.
        """
    @staticmethod
    def _decompose_sequence_numba_flat(
        cue_sequence: NDArray[np.uint8],
        motifs_flat: NDArray[np.uint8],
        motif_starts: NDArray[np.int32],
        motif_lengths: NDArray[np.int32],
        motif_indices: NDArray[np.int32],
        max_trials: int,
    ) -> tuple[NDArray[np.int32], int]:
        """Decomposes a long sequence of Virtual Reality (VR) wall cues into individual trial motifs.

        This is a worker function used to speed up decomposition via numba-acceleration.

        Args:
            cue_sequence: The full cue sequence to decompose.
            motifs_flat: All motifs concatenated into a single 1D array.
            motif_starts: Starting index of each motif in motifs_flat.
            motif_lengths: The length of each motif.
            motif_indices: Original indices of motifs (before sorting).
            max_trials: The maximum number of trials that can make up the cue sequence.

        Returns:
            A tuple of two elements. The first element stores the array of trial type-indices (the sequence of trial
            type indices). The second element stores the total number of trials extracted from the cue sequence.
        """
    def _toggle_lick_guidance(self, enable_guidance: bool) -> None:
        """Sets the VR task to either require the animal to lick in the reward zone to get water or to get rewards
        automatically upon entering the reward zone.

        Args:
            enable_guidance: Determines whether the animal must lick (False) to get water rewards or whether it will
                receive rewards automatically when entering the zone (True).
        """
    def _toggle_show_reward(self, show_reward: bool) -> None:
        """Sets the VR task to either show or hide the reward zone boundary (wall) with which the animal needs to
        collide to receive guided water rewards.

        To receive water rewards in the guided mode, the animal has to collide with the invisible wall, typically
        located in the middle of the reward zone. This method is used to optionally make that wall visible to the
        animal, which may be desirable for certain tasks.

        Args:
            show_reward: Determines whether the reward zone collision wall is visible to the animal (True) or hidden
                from the animal (False).
        """
    def _change_system_state(self, new_state: int) -> None:
        """Updates and logs the new Mesoscope-VR system state.

        This method is used internally to timestamp and log system state changes, such as transitioning between
        rest and run states during experiment runtimes.

        Args:
            new_state: The byte-code for the newly activated Mesoscope-VR system state.
        """
    def change_runtime_state(self, new_state: int) -> None:
        """Updates and logs the new runtime state (stage).

        Use this method to timestamp and log runtime state (stage) changes, such as transitioning between different
        task goals or experiment phases.

        Args:
            new_state: The integer byte-code for the new runtime state. The code will be serialized as an uint8
                value, so only values between 0 and 255 inclusive are supported.
        """
    def idle(self) -> None:
        """Switches the Mesoscope-VR system to the idle state.

        In the idle state, the break is engaged to prevent the animal from moving the wheel and the screens are turned
        Off. Both torque and encoder monitoring are disabled. Note, idle state is designed to be used exclusively during
        periods where the runtime pauses and does not generate any valid data.

        Notes:
            Unlike the other VR states, setting the system to 'idle' also automatically changes the runtime state to
            0 (idle).

            Idle Mesoscope-VR state is hardcoded as '0'.
        """
    def rest(self) -> None:
        """Switches the Mesoscope-VR system to the rest state.

        In the rest state, the break is engaged to prevent the animal from moving the wheel. The encoder module is
        disabled, and instead the torque sensor is enabled. The VR screens are switched off, cutting off light emission.

        Notes:
            Rest Mesoscope-VR state is hardcoded as '1'.
        """
    def run(self) -> None:
        """Switches the Mesoscope-VR system to the run state.

        In the run state, the break is disengaged to allow the animal to freely move the wheel. The encoder module is
        enabled to record motion data, and the torque sensor is disabled. The VR screens are switched on to render the
        VR environment.

        Notes:
            Run Mesoscope-VR state is hardcoded as '2'.
        """
    def lick_train(self) -> None:
        """Switches the Mesoscope-VR system to the lick training state.

        In this state, the break is engaged to prevent the animal from moving the wheel. The encoder module is
        disabled, and the torque sensor is enabled. The VR screens are switched off, cutting off light emission.

        Notes:
            Lick training Mesoscope-VR state is hardcoded as '3'.

            Calling this method automatically switches the runtime state to 255 (active training).
        """
    def run_train(self) -> None:
        """Switches the Mesoscope-VR system to the run training state.

        In this state, the break is disengaged, allowing the animal to run on the wheel. The encoder module is
        enabled, and the torque sensor is disabled. The VR screens are switched off, cutting off light emission.

         Notes:
            Run training Mesoscope-VR state is hardcoded as '4'.

            Calling this method automatically switches the runtime state to 255 (active training).
        """
    def update_visualizer_thresholds(self, speed_threshold: np.float64, duration_threshold: np.float64) -> None:
        """Instructs the data visualizer to update the displayed running speed and running epoch duration thresholds
        using the input data.

        This method is used by the run training runtime to synchronize the visualizer with the actively used thresholds.

        Args:
            speed_threshold: The speed threshold in centimeters per second. Specifies how fast the animal should be
                running to satisfy the current task conditions.
            duration_threshold: The running epoch duration threshold in seconds. Specifies how long the animal must
                maintain the above-threshold speed to satisfy the current task conditions.
        """
    def _deliver_reward(self, reward_size: float = 5.0) -> None:
        """Uses the solenoid valve to deliver the requested volume of water in microliters.

        Args:
            reward_size: The volume of water to deliver, in microliters. If this argument is set to None, the method
                will use the same volume as used during the previous reward delivery or as set via the GUI.
        """
    def _simulate_reward(self) -> None:
        """Uses the buzzer controlled by the valve module to deliver an audible tone without delivering any water
        reward.

        This method is used when the animal refuses to consume water rewards during training or experiment runtimes. The
        tone notifies the animal that it performs the task as expected, while simultaneously minimizing water reward
        wasting.
        """
    def resolve_reward(self, reward_size: float = 5.0) -> bool:
        """Depending on the current number of unconsumed rewards and runtime configuration, either delivers or simulates
        the requested volume of water reward.

        This method functions as a wrapper that decides whether to call the _simulate_reward() or _deliver_reward()
        method. This ensures that each external water delivery call complies with the runtime's policy on delivering
        rewards when the animal is not consuming them.

        Args:
            reward_size: The volume of water to deliver, in microliters.

        Returns:
            True if the method delivers the water reward, False if it simulates it.
        """
    def runtime_cycle(self) -> None:
        """Sequentially carries out all cyclic Mesoscope-VR runtime tasks.

        This base cycle method should be called by the runtime logic function as part of its main runtime loop. Calling
        this method synchronizes various assets used by the class instance, such as the GUI, Unity game engine, and the
        visualizer. Also, it is used to monitor critical external assets, such as the Mesoscope and, if necessary,
        pause the runtime and request user intervention.
        """
    def _data_cycle(self) -> None:
        """Queries and synchronizes changes to animal runtime behavior metrics with Unity and the visualizer class.

        This method reads the data sent by low-level data acquisition modules and updates class attributes used to
        support runtime logic, data visualization, and Unity VR task. If necessary, it directly communicates the updates
        to Unity via MQTT and to the visualizer through appropriate methods.
        """
    def _unity_cycle(self) -> None:
        """Synchronizes the state of the Unity-managed Virtual Reality environment with the runtime state.

        This method receives valve activation (reward delivery) commands and state messages from the Unity game engine.
        Depending on the received message, it either directly activates the necessary routine (e.g., water delivery)
        or configures runtime state trackers and returns to the main runtime cycle method to handle the state
        transition.

        Notes:
            This method has been introduced in version 2.0.0 to aggregate all Unity communication (via MQTT) at the
            highest level of the runtime hierarchy (the main runtime management class). This prevents an error with the
            Mosquitto MQTT broker, where the broker arbitrarily disconnected clients running in remote processes.

            During each runtime cycle, the method receives and parses exactly one message stored in the
            MQTTCommunication class buffer. This is in line with how all other communication classes in SL and Ataraxis
            projects behave.
        """
    def _ui_cycle(self) -> None:
        """Queries the state of various GUI components and adjusts the runtime behavior accordingly.

        This utility method cycles through various user-addressable runtime components and, depending on corresponding
        UI states, executes the necessary functionality or updates associated parameters. In essence, calling this
        method synchronizes the runtime with the state of the runtime control GUI.

        Notes:
            This method is designed to be called repeatedly as part of the main runtime cycle loop (via the user-facing
            runtime_cycle() method).
        """
    def _mesoscope_cycle(self) -> None:
        """Checks whether mesoscope frame acquisition is active and, if not, emergency pauses the runtime.

        This method is designed to be called repeatedly as part of the system runtime cycle. It monitors mesoscope
        frame acquisition triggers, and if it detects an acquisition pause longer than ~300 milliseconds, it activates
        the emergency pause state, similar to how Unity termination messages are handled by the _unity_cycle() method.
        """
    def _pause_runtime(self) -> None:
        """Pauses the managed runtime.

        This method is typically called if the user encounters a non-critical error with one of the runtime assets.
        Pausing the runtime allows the user to fix the error and resume the runtime, minimizing data loss and
        eliminating the need to re-run runtime setup procedures.

        Notes:
            When the runtime is paused, the Mesoscope-VR system locks into its internal cycle loop and does not release
            control to the main runtime logic loop. Additionally, it switches the system into the 'idle' state,
            effectively interrupting any ongoing task. The GUI and all external assets (Unity, Mesoscope) continue
            to function as normal unless manually terminated by the user.

            Any water dispensed through the valve during the paused state does not count against the water reward limit
            of the executed task.
        """
    def _resume_runtime(self) -> None:
        """Resumes the managed runtime.

        This method restores the system back to the original running state after it has been paused with the
        _pause_runtime() method. As part of this process, it also updates the 'paused_time' to reflect the time, in
        seconds, spent in the paused state.
        """
    def _terminate_runtime(self) -> None:
        """Verifies that the user intends to abort the runtime via terminal prompt and, if so, sets the runtime into
        the termination mode.

        When the runtime is switched into the termination mode, it will sequentially escape all internal and external
        cycle loops and attempt to perform a graceful shutdown procedure.
        """
    def setup_lick_guidance(
        self, initial_guided_trials: int = 3, failed_trials_threshold: int = 9, recovery_guided_trials: int = 3
    ) -> None:
        """Configures the trial guidance logic that should be used during runtime.

        This service method is designed to be used by the experiment runtime logic function to configure the lick
        guidance during runtime. Since each experiment state (phase) can use different lick guidance parameters, this
        method should be called at each experiment state (phase) transition.

        Notes:
            Once this method configures the Mesoscope-VR guidance handling logic, the system will maintain that logic
            internally until the experiment runtime ends or this method is called again to reconfigure the guidance
            parameters.

        Args:
            initial_guided_trials: The number of trials for which to enable the lick guidance as part of this method's
                runtime. Specifically, these many trials following the call of this method will be executed in the lick
                guidance mode.
            failed_trials_threshold: The number of trials the animal must fail (not receive a reward) in a row to
                trigger the recovery mode. The recovery mode re-enables lick guidance for the number of trials
                specified by the 'recovery_guided_trials' argument.
            recovery_guided_trials: The number of trials for which to enable lick guidance when the runtime activates
                the recovery mode.

        """
    @property
    def terminated(self) -> bool:
        """Returns True if the runtime is in the termination mode.

        This property is used by external logic functions to detect and execute runtime termination commands issued via
        GUI.
        """
    @property
    def running_speed(self) -> np.float64:
        """Returns the current running speed of the animal in centimeters per second."""
    @property
    def speed_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the running speed threshold during run training."""
    @property
    def duration_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the duration threshold during run training."""
    @property
    def dispensed_water_volume(self) -> float:
        """Returns the total volume of water, in microliters, dispensed by the valve during the current runtime."""

def lick_training_logic(
    experimenter: str,
    project_name: str,
    animal_id: str,
    animal_weight: float,
    minimum_reward_delay: int = 6,
    maximum_reward_delay: int = 18,
    maximum_water_volume: float = 1.0,
    maximum_training_time: int = 20,
    maximum_unconsumed_rewards: int = 1,
    load_previous_parameters: bool = False,
) -> None:
    """Encapsulates the logic used to train animals to operate the lick port.

    The lick training consists of delivering randomly spaced 5 uL water rewards via the solenoid valve to teach the
    animal that water comes out of the lick port. Each reward is delivered after a pseudorandom delay. Reward delay
    sequence is generated before training runtime by sampling a uniform distribution that ranges from
    'minimum_reward_delay' to 'maximum_reward_delay'. The training continues either until the valve
    delivers the 'maximum_water_volume' in milliliters or until the 'maximum_training_time' in minutes is reached,
    whichever comes first.

    Args:
        experimenter: The ID (net-ID) of the experimenter conducting the training.
        project_name: The name of the project to which the trained animal belongs.
        animal_id: The numeric ID of the animal being trained.
        animal_weight: The weight of the animal, in grams, at the beginning of the training session.
        minimum_reward_delay: The minimum time, in seconds, that has to pass between delivering two consecutive rewards.
        maximum_reward_delay: The maximum time, in seconds, that can pass between delivering two consecutive rewards.
        maximum_water_volume: The maximum volume of water, in milliliters, that can be delivered during this runtime.
        maximum_training_time: The maximum time, in minutes, to run the training.
        maximum_unconsumed_rewards: The maximum number of rewards that can be delivered without the animal consuming
            them, before reward delivery (but not the training!) pauses until the animal consumes available rewards.
            If this is set to a value below 1, the unconsumed reward limit will not be enforced. A value of 1 means
            the animal has to consume each reward before getting the next reward.
        load_previous_parameters: Determines whether to override all input runtime-defining parameters with the
            parameters used during the previous session. If this is set to True, the function will ignore most input
            parameters and will instead load them from the cached session descriptor of the previous session. If the
            descriptor is not available, the function will fall back to using input parameters.
    """

def run_training_logic(
    experimenter: str,
    project_name: str,
    animal_id: str,
    animal_weight: float,
    initial_speed_threshold: float = 0.5,
    initial_duration_threshold: float = 0.5,
    speed_increase_step: float = 0.05,
    duration_increase_step: float = 0.05,
    increase_threshold: float = 0.1,
    maximum_water_volume: float = 1.0,
    maximum_training_time: int = 40,
    maximum_idle_time: float = 0.5,
    maximum_unconsumed_rewards: int = 1,
    load_previous_parameters: bool = False,
) -> None:
    """Encapsulates the logic used to train animals to run on the wheel treadmill while being head-fixed.

    The run training consists of making the animal run on the wheel with a desired speed, in centimeters per second,
    maintained for the desired duration of time, in seconds. Each time the animal satisfies the speed and duration
    thresholds, it receives 5 uL of water reward, and the speed and duration trackers reset for the next training
    'epoch'. Each time the animal receives 'increase_threshold' of water, the speed and duration thresholds increase to
    make the task progressively more challenging. The training continues either until the training time exceeds the
    'maximum_training_time', or the animal receives the 'maximum_water_volume' of water, whichever happens earlier.

    Args:
        experimenter: The id of the experimenter conducting the training.
        project_name: The name of the project to which the trained animal belongs.
        animal_id: The numeric ID of the animal being trained.
        animal_weight: The weight of the animal, in grams, at the beginning of the training session.
        initial_speed_threshold: The initial running speed threshold, in centimeters per second, that the animal must
            maintain to receive water rewards.
        initial_duration_threshold: The initial duration threshold, in seconds, that the animal must maintain
            above-threshold running speed to receive water rewards.
        speed_increase_step: The step size, in centimeters per second, by which to increase the speed threshold each
            time the animal receives 'increase_threshold' milliliters of water.
        duration_increase_step: The step size, in seconds, by which to increase the duration threshold each time the
            animal receives 'increase_threshold' milliliters of water.
        increase_threshold: The volume of water received by the animal, in milliliters, after which the speed and
            duration thresholds are increased by one step. Note, the animal will at most get 'maximum_water_volume' of
            water, so this parameter effectively controls how many increases will be made during runtime, assuming the
            maximum training time is not reached.
        maximum_water_volume: The maximum volume of water, in milliliters, that can be delivered during this runtime.
        maximum_training_time: The maximum time, in minutes, to run the training.
        maximum_idle_time: The maximum time, in seconds, the animal's speed can be below the speed threshold to
            still receive water rewards. This parameter is designed to help animals with a distinct 'step' pattern to
            not lose water rewards due to taking many large steps, rather than continuously running at a stable speed.
            This parameter allows the speed to dip below the threshold for at most this number of seconds, for the
            'running epoch' to not be interrupted.
        maximum_unconsumed_rewards: The maximum number of rewards that can be delivered without the animal consuming
            them, before reward delivery (but not the training!) pauses until the animal consumes available rewards.
            If this is set to a value below 1, the unconsumed reward limit will not be enforced. A value of 1 means
            the animal has to consume all rewards before getting the next reward.
        load_previous_parameters: Determines whether to override all input runtime-defining parameters with the
            parameters used during the previous session. If this is set to True, the function will ignore most input
            parameters and will instead load them from the cached session descriptor of the previous session. If the
            descriptor is not available, the function will fall back to using input parameters.
    """

def experiment_logic(
    experimenter: str,
    project_name: str,
    experiment_name: str,
    animal_id: str,
    animal_weight: float,
    maximum_unconsumed_rewards: int = 1,
) -> None:
    """Encapsulates the logic used to run experiments via the Mesoscope-VR system.

    This function can be used to execute any valid experiment using the Mesoscope-VR system. Each experiment should be
    broken into one or more experiment states (phases), such as 'baseline', 'task' and 'cooldown'. Furthermore, each
    experiment state can use one or more Mesoscope-VR system states. Currently, the system has two experiment states:
    rest (1) and run (2). The states are used to broadly configure the Mesoscope-VR system, and they determine which
    components (modules) are active and what data is collected (see library ReadMe for more details on system states).

    Primarily, this function is concerned with iterating over the states stored inside the experiment configuration file
    loaded using the 'experiment_name' argument value. Each experiment and Mesoscope-VR system state combination is
    maintained for the requested duration of seconds. Once all states have been executed, the experiment runtime ends.
    Under this design pattern, each experiment is conceptualized as a sequence of states.

    Notes:
        During experiment runtimes, the task logic and the Virtual Reality world are resolved via the Unity game engine.
        This function itself does not resolve the task logic, it is only concerned with iterating over experiment
        states and controlling the Mesoscope-VR system.

    Args:
        experimenter: The id of the experimenter conducting the experiment.
        project_name: The name of the project for which the experiment is conducted.
        experiment_name: The name or ID of the experiment to be conducted. Note, must match the name of the experiment
            configuration file stored under the 'configuration' project-specific directory.
        animal_id: The numeric ID of the animal participating in the experiment.
        animal_weight: The weight of the animal, in grams, at the beginning of the experiment session.
        maximum_unconsumed_rewards: The maximum number of rewards that can be delivered without the animal consuming
            them, before reward delivery (but not the experiment!) pauses until the animal consumes available rewards.
            If this is set to a value below 1, the unconsumed reward limit will not be enforced. A value of 1 means
            the animal has to consume each reward before getting the next reward.
    """

def window_checking_logic(experimenter: str, project_name: str, animal_id: str) -> None:
    """Encapsulates the logic used to verify the surgery quality (cranial window) and generate the initial snapshot of
    the Mesoscope-VR system configuration for a newly added animal of the target project.

    This function is used when new animals are added to the project, before any other training or experiment runtime.
    Primarily, it is used to verify that the surgery went as expected and the animal is fit for providing high-quality
    scientific data. As part of this process, the function also generates the snapshot of zaber motor positions, the
    mesoscope objective position, and the red-dot alignment screenshot to be reused by future sessions.

    Notes:
        This function largely behaves similar to all other training and experiment session runtimes. However, it does
        not use most of the Mesoscope-VR components and does not make most of the runtime data files typically generated
        by other sessions. All window checking sessions are automatically marked as 'incomplete' and excluded from
        automated data processing.

    Args:
        experimenter: The id of the experimenter conducting the window checking session.
        project_name: The name of the project to which the checked animal belongs.
        animal_id: The numeric ID of the animal whose cranial window is being checked.
    """

def maintenance_logic() -> None:
    """Encapsulates the logic used to maintain various components of the Mesoscope-VR system.

    This runtime is primarily used to verify and, if necessary, recalibrate the water valve between training or
    experiment days and to maintain the surface material of the running wheel.
    """
