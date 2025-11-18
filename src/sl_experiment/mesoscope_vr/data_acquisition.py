"""This module provides the assets for executing data acquisition sessions and maintenance runtimes via the
Mesoscope-VR data acquisition system.
"""

import os
import copy
from enum import IntEnum, StrEnum
import json
from json import dumps
import shutil as sh
from pathlib import Path
import tempfile

from tqdm import tqdm
from numba import njit
import numpy as np
from numpy.typing import NDArray
from ataraxis_time import PrecisionTimer, TimerPrecisions, TimestampFormats, convert_time, get_timestamp
from sl_shared_assets import (
    SessionData,
    SessionTypes,
    ZaberPositions,
    MesoscopePositions,
    RunTrainingDescriptor,
    LickTrainingDescriptor,
    MesoscopeHardwareState,
    MesoscopeExperimentState,
    MesoscopeExperimentTrial,
    WindowCheckingDescriptor,
    MesoscopeSystemConfiguration,
    MesoscopeExperimentDescriptor,
    MesoscopeExperimentConfiguration,
)
from ataraxis_base_utilities import LogLevel, console
from ataraxis_data_structures import DataLogger, LogPackage
from ataraxis_communication_interface import MQTTCommunication, MicroControllerInterface

from .tools import MesoscopeData, CachedMotifDecomposer, get_system_configuration
from .runtime_ui import RuntimeControlUI
from .visualizers import BehaviorVisualizer
from .maintenance_ui import MaintenanceControlUI
from .binding_classes import ZaberMotors, VideoSystems, MicroControllerInterfaces
from ..shared_components import (
    WaterLog,
    SurgeryLog,
    BrakeInterface,
    ValveInterface,
    get_version_data,
    get_animal_project,
    get_project_experiments,
)
from .data_preprocessing import purge_session, preprocess_session_data, rename_mesoscope_directory

_RESPONSE_DELAY: int = 2000
"""Specifies the number of milliseconds to delay showing the response prompt after showing a message that requires 
user interaction."""

_RENDERING_SEPARATION_DELAY = 500
"""Specifies the number of milliseconds to delay between rendering console outputs (stderr) and non-console outputs 
(stdout) to prevent the two renders from overlapping."""

_response_delay_timer = PrecisionTimer(precision=TimerPrecisions.MILLISECOND)
"""The PrecisionTimer instance used to support the proper rendering of all terminal outputs used during runtime."""


# Defines shared methods to make their use consistent between window checking and other runtimes.
def _generate_mesoscope_position_snapshot(session_data: SessionData, mesoscope_data: MesoscopeData) -> None:
    """Generates a precursor mesoscope_positions.yaml file and forces the user to update it to reflect
    the current mesoscope's imaging position coordinates.

    Args:
        session_data: The SessionData instance that defines the session for which the snapshot is generated.
        mesoscope_data: The MesoscopeData instance that defines the current Mesoscope-VR system's configuration.
    """
    # Loads the previous position data into memory.
    previous_mesoscope_positions: MesoscopePositions = MesoscopePositions.from_yaml(
        file_path=mesoscope_data.vrpc_data.mesoscope_positions_path
    )

    # Forces the user to update the cached mesoscope position coordinates with the current data.
    message = (
        f"Update the data inside the mesoscope_positions.yaml file stored under the {session_data.session_name} "
        f"session's 'raw_data' directory to reflect the current mesoscope objective position."
    )
    console.echo(message=message, level=LogLevel.INFO)
    # Delays for 2 seconds to ensure the user reads the message before continuing.
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Defines the error message for file formatting issues
    io_error_message = (
        f"Unable to read the data from the {session_data.session_name} session's mesoscope_positions.yaml file. This "
        f"indicates that the file was mis-formatted during editing. Make sure the file contents follow the .YAML "
        f"format before retrying."
    )

    # Defines the validation error message for unchanged positions
    validation_error_message = (
        f"Failed to verify that the mesoscope_positions.yaml file stored inside the {session_data.session_name} "
        f"session's raw_data directory has been updated to include the mesoscope imaging coordinates used during "
        f"runtime. Edit the mesoscope_positions.yaml file to update the position fields with coordinates "
        f"displayed in the ScanImage software or on the ThorLabs pad. Make sure to save the changes by pressing "
        f"the 'CTRL+S' combination."
    )

    # Continuously attempts to read and validate the Mesoscope positions data until successful
    while True:
        # Attempts to read the current mesoscope positions from the session file
        # noinspection PyBroadException
        try:
            mesoscope_positions: MesoscopePositions = MesoscopePositions.from_yaml(
                file_path=session_data.raw_data.mesoscope_positions_path,
            )
        except Exception:
            console.echo(message=io_error_message, level=LogLevel.ERROR)
            input("Enter anything to continue: ")
            continue

        # Validates that the user has updated the position data
        if (
            mesoscope_positions.mesoscope_x != previous_mesoscope_positions.mesoscope_x
            or mesoscope_positions.mesoscope_y != previous_mesoscope_positions.mesoscope_y
            or mesoscope_positions.mesoscope_z != previous_mesoscope_positions.mesoscope_z
            or mesoscope_positions.mesoscope_roll != previous_mesoscope_positions.mesoscope_roll
            or mesoscope_positions.mesoscope_fast_z != previous_mesoscope_positions.mesoscope_fast_z
            or mesoscope_positions.mesoscope_tip != previous_mesoscope_positions.mesoscope_tip
            or mesoscope_positions.mesoscope_tilt != previous_mesoscope_positions.mesoscope_tilt
            or mesoscope_positions.laser_power_mw != previous_mesoscope_positions.laser_power_mw
            or mesoscope_positions.red_dot_alignment_z != previous_mesoscope_positions.red_dot_alignment_z
        ):
            break

        # If positions match, request the user to update the file
        console.echo(message=validation_error_message, level=LogLevel.ERROR)
        input("Enter anything to continue: ")

    # Copies the updated mesoscope positions data into the animal's persistent directory.
    sh.copy2(
        src=session_data.raw_data.mesoscope_positions_path,
        dst=mesoscope_data.vrpc_data.mesoscope_positions_path,
    )


def _generate_zaber_snapshot(
    session_data: SessionData, mesoscope_data: MesoscopeData, zaber_motors: ZaberMotors
) -> None:
    """Creates a snapshot of the current Zaber motor positions and saves it as a zaber_positions.yaml file.

    Args:
        zaber_motors: The ZaberMotors instance that manages the Zaber assets used by the session for which the
            snapshot is generated.
        session_data: The SessionData instance that defines the session for which the snapshot is generated.
        mesoscope_data: The MesoscopeData instance that defines the current Mesoscope-VR system's configuration.
    """
    # If at least one of the managed motor groups is not connected, does not run the snapshot generation sequence.
    if not zaber_motors.is_connected:
        return

    # Generates the snapshot
    zaber_positions = zaber_motors.generate_position_snapshot()

    # Saves the newly generated file both to the persistent directory and to the session directory. Note, saving to the
    # persistent data directory automatically overwrites any existing position file.
    zaber_positions.to_yaml(file_path=mesoscope_data.vrpc_data.zaber_positions_path)
    zaber_positions.to_yaml(file_path=session_data.raw_data.zaber_positions_path)

    message = "Zaber motor positions: Saved."
    console.echo(message=message, level=LogLevel.SUCCESS)


def _setup_zaber_motors(zaber_motors: ZaberMotors) -> None:
    """If necessary, carries out the Zaber motor setup and positioning sequence.

    Args:
        zaber_motors: The ZaberMotors instance that manages the Zaber motors used during runtime.
    """
    # Determines whether to carry out the Zaber motor positioning sequence.
    message = (
        "Do you want to carry out the Zaber motor setup sequence for this runtime? Only enter 'no' if the animal is "
        "already positioned inside the Mesoscope enclosure."
    )
    console.echo(message=message, level=LogLevel.INFO)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)

    # Blocks until a valid answer is received from the user.
    while True:
        answer = input("Enter 'yes' or 'no': ").lower()[0]

        if answer.lower() == "n":
            # Aborts method runtime, as no further Zaber setup is required.
            return

        if answer.lower() == "y":
            # Proceeds with the setup sequence.
            break

    # Since it is now possible to shut down Zaber motors without fixing HeadBarRoll position, requests the user
    # to verify this manually.
    message = (
        "Check that the HeadBarRoll motor has a positive (>0) angle. If the angle is negative (<0), the motor will "
        "collide with the stopper during homing, which will DAMAGE the motor."
    )
    console.echo(message=message, level=LogLevel.WARNING)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Initializes the Zaber positioning sequence. This relies heavily on user feedback to confirm that it is
    # safe to proceed with motor movements.
    message = (
        "Preparing to move Zaber motors into mounting position. Remove the mesoscope objective, swivel out the "
        "VR screens, and make sure the animal is NOT mounted in the Mesoscope's enclosure."
    )
    console.echo(message=message, level=LogLevel.WARNING)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Homes all managed motors in parallel.
    zaber_motors.prepare_motors()

    # Moves all motors to the animal mounting position.
    zaber_motors.mount_position()

    message = "Motor Positioning: Complete."
    console.echo(message=message, level=LogLevel.SUCCESS)

    # Gives the user time to mount the animal and requires confirmation before proceeding further.
    message = (
        "Preparing to move the motors into the imaging position. Mount the animal onto the VR rig. Do NOT "
        "adjust any motors manually at this time. Do NOT install the mesoscope objective."
    )
    console.echo(message=message, level=LogLevel.WARNING)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Restores all motors to the positions used during the previous session's runtime.
    zaber_motors.restore_position()

    message = "Motor Positioning: Complete."
    console.echo(message=message, level=LogLevel.SUCCESS)


def _reset_zaber_motors(zaber_motors: ZaberMotors) -> None:
    """If necessary, carries out the Zaber motor parking and shutdown sequence.

    Args:
        zaber_motors: The ZaberMotors instance that manages the Zaber motors used during runtime.
    """
    # If at least one of the managed motor groups is not connected, does not run the reset sequence.
    if not zaber_motors.is_connected:
        return

    # Determines whether to carry out the Zaber motor shutdown sequence.
    message = (
        "Do you want to carry out Zaber motor shutdown sequence? If ending a successful runtime, enter 'yes'. If "
        "terminating a failed runtime to restart it, enter 'no'. Note! Entering 'yes' does NOT move any motors."
    )
    console.echo(message=message, level=LogLevel.INFO)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)

    while True:
        answer = input("Enter 'yes' or 'no': ").lower()[0]

        # Continues with the rest of the shutdown runtime
        if answer.lower() == "y":
            break

        # Ends the runtime, as there is no need to move Zaber motors.
        if answer.lower() == "n":
            # Disconnects from Zaber motors. This does not change motor positions but does lock (park) all motors
            # before disconnecting.
            zaber_motors.disconnect()
            return

    # Helps with removing the animal from the enclosure by retracting the lick-port in the Y-axis (moving it away
    # from the animal).
    message = "Retracting the lick-port away from the animal..."
    console.echo(message=message, level=LogLevel.INFO)
    zaber_motors.unmount_position()

    message = "Motor Positioning: Complete."
    console.echo(message=message, level=LogLevel.SUCCESS)

    message = "Uninstall the mesoscope objective and REMOVE the animal from the Mesoscope's enclosure."
    console.echo(message=message, level=LogLevel.WARNING)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Moves all motors to the hardcoded parking positions.
    zaber_motors.park_position()

    # Disconnects from Zaber motors. This does not change motor positions but does lock (park) all motors
    # before disconnecting.
    zaber_motors.disconnect()

    message = "Zaber motors: Reset."
    console.echo(message=message, level=LogLevel.SUCCESS)


def _setup_mesoscope(session_data: SessionData, mesoscope_data: MesoscopeData) -> None:
    """Guides the user through the sequence of steps that prepares the Mesoscope for the data acquisition runtime.

    Args:
        session_data: The SessionData instance that defines the session for which the snapshot is generated.
        mesoscope_data: The MesoscopeData instance that defines the current Mesoscope-VR system's configuration.
    """
    # Determines whether the acquired session is a Window Checking session.
    window_checking: bool = session_data.session_type == SessionTypes.WINDOW_CHECKING

    # Step 0: Clears out the mesoscope_data directory.
    # Ensures that the mesoscope_data directory is reset before running the mesoscope's preparation sequence. To
    # minimize the risk of important data loss, this procedure now requires the user to remove the files manually.
    while True:
        existing_files = list(mesoscope_data.scanimagepc_data.mesoscope_data_path.glob("*"))

        if not existing_files:
            break

        message = (
            f"Unable to prepare the Mesoscope for the data acquisition runtime. The preparation requires the shared "
            f"'mesoscope_data' ScanImagePC directory to be empty, but the directory contains the following unexpected "
            f"files: {','.join(existing_files)}. Clear the directory from all existing files before proceeding."
        )
        console.echo(message=message, level=LogLevel.ERROR)
        _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
        input("Enter anything to continue: ")

    # Step 1: Resolves the imaging plane.
    # If the previous session's mesoscope positions were saved, loads the imaging coordinates and displays them to the
    # user
    if not window_checking and mesoscope_data.vrpc_data.mesoscope_positions_path.exists():
        previous_positions: MesoscopePositions = MesoscopePositions.from_yaml(
            file_path=mesoscope_data.vrpc_data.mesoscope_positions_path
        )
        message = (
            f"Follow the steps of the mesoscope preparation protocol available from the sl-protocols repository."
            f"Previous mesoscope coordinates were: x={previous_positions.mesoscope_x}, "
            f"y={previous_positions.mesoscope_y}, roll={previous_positions.mesoscope_roll}, "
            f"z={previous_positions.mesoscope_z}, fast_z={previous_positions.mesoscope_fast_z}, "
            f"tip={previous_positions.mesoscope_tip}, tilt={previous_positions.mesoscope_tilt}, "
            f"laser_power={previous_positions.laser_power_mw}, "
            f"red_dot_alignment_z={previous_positions.red_dot_alignment_z}."
        )
    elif not window_checking:
        message = (
            f"No previous mesoscope imaging position data found for the animal {session_data.animal_id}. Follow the "
            f"steps of the window checking protocol available from the sl-protocols repository to establish the "
            f"imaging plane for the animal."
        )
    else:
        message = (
            "Follow the steps of the window checking protocol available from the sl-protocols repository to establish "
            "the imaging plane for the animal."
        )
    console.echo(message=message, level=LogLevel.INFO)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Step 2: Generates the screenshot of the red-dot alignment and the cranial window.
    message = (
        "Generate the screenshot of the red-dot alignment, the imaging plane state (cell activity), and the "
        "ScanImage acquisition parameters by pressing the 'Win + PrtSc' combination."
    )
    console.echo(message=message, level=LogLevel.INFO)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Ensures that the screenshot is created before proceeding further.
    while True:
        screenshots = list(mesoscope_data.scanimagepc_data.meso_data_path.glob("*.png"))

        if screenshots:
            break

        message = (
            f"Unable to retrieve the screenshot from the ScanImage PC. Expected a single .png file inside the "
            f"'mesodata' ScanImagePC directory, but instead found {len(screenshots)} candidate files. Ensure that the "
            f"directory only stores the .png screenshot generated during the previous preparation step."
        )
        console.echo(message=message, level=LogLevel.ERROR)
        _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
        input("Enter anything to continue: ")

    # Transfers the screenshot to the session's mesoscope_frames directory
    screenshot_path = session_data.raw_data.window_screenshot_path
    sh.move(screenshots.pop(), screenshot_path)  # Moves the screenshot from the ScanImagePC to the VRPC

    # Copies the screenshot to the animal's persistent data directory so that it can be reused during the next
    # runtime.
    sh.copy2(screenshot_path, mesoscope_data.vrpc_data.window_screenshot_path)

    # Window checking sessions require special handling.
    if window_checking:
        # Since window checking may reveal that the evaluated animal is not fit for participating in experiments,
        # optionally allows aborting the runtime early for window checking sessions.
        message = "Do you want to generate the ROI and MotionEstimator snapshots for this animal?"
        console.echo(message=message, level=LogLevel.INFO)
        _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)

        # Blocks until a valid answer is received from the user
        while True:
            answer = input("Enter 'yes' or 'no': ").lower()[0]

            if answer.lower() == "n":
                # Aborts the runtime if the user does not intend to generate the ROI and MotionEstimator data
                console.echo(message="Mesoscope preparation: Complete.", level=LogLevel.SUCCESS)
                return

            if answer.lower() == "y":
                # Proceeds with the metadata file acquisition sequence
                break

        # Ensures that kinase is removed, while the phosphatase is present. This aborts the runtime
        # after generating the zstack.tiff and the MotionEstimator.me files.
        mesoscope_data.scanimagepc_data.kinase_path.unlink(missing_ok=True)
        mesoscope_data.scanimagepc_data.phosphatase_path.touch()

    else:
        # For all other runtimes, resets the kinase and phosphatase markers before instructing the user to start the
        # acquisition preparation function.
        mesoscope_data.scanimagepc_data.kinase_path.unlink(missing_ok=True)
        mesoscope_data.scanimagepc_data.phosphatase_path.unlink(missing_ok=True)

    # Step 3: Generates the new MotionEstimator file and arms the mesoscope for acquisition.
    message = (
        "Call the 'setupAcquisition(hSI, hSICtl)' function via MATLAB's command line interface on the ScanImagePC to "
        "prepare and arm the mesoscope to acquire the session's data."
    )
    console.echo(message=message, level=LogLevel.INFO)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # The preparation function generates 3 files: MotionEstimator.me, fov.roi, and zstack.tiff.
    target_files = (
        mesoscope_data.scanimagepc_data.mesoscope_data_path.joinpath("MotionEstimator.me"),
        mesoscope_data.scanimagepc_data.mesoscope_data_path.joinpath("fov.roi"),
        mesoscope_data.scanimagepc_data.mesoscope_data_path.joinpath("zstack.tiff"),
    )

    # Waits until the necessary files are generated on the ScanImagePC.
    while True:
        missing_files = [f for f in target_files if not f.exists()]

        if not missing_files:
            break

        missing_names = ", ".join(f.name for f in missing_files)

        message = (
            f"Unable to confirm that the ScanImagePC has generated the required acquisition data files, as the "
            f"following expected files are missing from the 'mesoscope_data' directory: {missing_names}. Rerun the "
            f"setupAcquisition(hSI, hSICtl) function to generate the requested files."
        )
        console.echo(message=message, level=LogLevel.ERROR)
        _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
        input("Enter anything to continue: ")

    console.echo(message="Mesoscope preparation: Complete.", level=LogLevel.SUCCESS)


def _verify_descriptor_update(
    descriptor: MesoscopeExperimentDescriptor
    | LickTrainingDescriptor
    | RunTrainingDescriptor
    | WindowCheckingDescriptor,
    session_data: SessionData,
    mesoscope_data: MesoscopeData,
) -> None:
    """Caches the input session's descriptor to disk and forces the user supervising the session's data acquisition to
    update the data stored inside the cached descriptor file with the notes made during runtime.

    Args:
        descriptor: The session_descriptor.yaml-convertible instance to cache to the acquired session's data directory.
        session_data: The SessionData instance that defines the session for which the descriptor file is generated.
        mesoscope_data: The MesoscopeData instance that defines the current Mesoscope-VR system's configuration.
    """
    # Saves the descriptor as a .yaml file.
    descriptor.to_yaml(file_path=session_data.raw_data.session_descriptor_path)
    console.echo(message="Session descriptor precursor file: Created.", level=LogLevel.SUCCESS)

    # Instructs the user to add user-collected data to the cached descriptor file.
    message = (
        f"Update the data inside the session_descriptor.yaml file stored under the {session_data.session_name} "
        f"session's 'raw_data' directory to include the notes and data collected by the user supervising the runtime "
        f"during the session's data acquisition."
    )

    console.echo(message=message, level=LogLevel.INFO)
    _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
    input("Enter anything to continue: ")

    # Defines error messages for file operations
    io_error_message = (
        f"Unable to read the data from the {session_data.session_name} session's session_descriptor.yaml file. This "
        f"indicates that the file was mis-formatted during editing. Make sure the file contents follow the .YAML "
        f"format before retrying."
    )
    validation_error_message = (
        f"Failed to verify that the session_descriptor.yaml file stored inside the {session_data.session_name} "
        f"session's raw_data directory has been updated to include the supervising user's notes taken during "
        f"runtime. Manually edit the session_descriptor.yaml file and replace the default text under the "
        f"'experimenter_notes' field with the notes taken during runtime. Make sure to save the changes by pressing "
        f"the 'CTRL+S' combination."
    )

    # Continuously attempts to read and validate the session descriptor until successful
    while True:
        # Attempts to read the session's descriptor data from the .yaml file.
        try:
            descriptor = descriptor.from_yaml(file_path=session_data.raw_data.session_descriptor_path)
        except Exception:
            console.echo(message=io_error_message, level=LogLevel.ERROR)
            input("Enter anything to continue: ")
            continue

        # Validates that the user has updated the experimenter notes
        # noinspection PyUnresolvedReferences
        if "Replace this with your notes." not in descriptor.experimenter_notes:
            break

        # If validation fails, prompt the user to update the file
        console.echo(message=validation_error_message, level=LogLevel.ERROR)
        input("Enter anything to continue: ")

    # If the descriptor has passed the verification, copies it up to the animal's persistent directory. This is a
    # feature primarily used during training to restore the training parameters between training sessions of the
    # same type.
    sh.copy2(
        src=session_data.raw_data.session_descriptor_path,
        dst=mesoscope_data.vrpc_data.session_descriptor_path,
    )


class _MesoscopeVRStates(IntEnum):
    """Defines the set of codes used by the Mesoscope-VR data acquisition system to communicate its runtime state."""

    IDLE = 0
    """The system is currently not conducting a data acquisition session."""
    REST = 1
    """The system is conducting the 'rest' period of an experiment session."""
    RUN = 2
    """The system is conducting the 'run' period of an experiment session."""
    LICK_TRAINING = 3
    """The system is conducting the lick training session."""
    RUN_TRAINING = 4
    """The system is conducting the run training session."""

    @classmethod
    def to_dict(cls) -> dict[str, int]:
        """Converts the instance's data to a dictionary mapping, replacing underscores with spaces."""
        return {member.name.lower().replace("_", " "): member.value for member in cls}


class _MesoscopeVRMQTTTopics(StrEnum):
    """Defines the set of MQTT topics used by the Mesoscope-VR data acquisition system to communicate with the Unity
    game engine.

    Notes:
        The topics defined in this enumeration are used in addition to the topic defined by the hardware module
        interfaces used by the system.
    """

    UNITY_TERMINATION = "Gimbl/Session/Stop"
    """Stops the Unity game session."""
    UNITY_STARTUP = "Gimbl/Session/Start"
    """Starts the Unity game session."""
    CUE_SEQUENCE = "CueSequence/"
    """The topic to which Unity sends the sequence of VR cues used by the current game session."""
    CUE_SEQUENCE_REQUEST = "CueSequenceTrigger/"
    """Requests Unity to send the sequence of VR cues used by the current game session."""
    DISABLE_GUIDANCE = "MustLick/True/"
    """Requests Unity to enable the task guidance mode."""
    ENABLE_GUIDANCE = "MustLick/False/"
    """Requests Unity to disable the task guidance mode."""
    SHOW_REWARD_ZONE_BOUNDARY = "VisibleMarker/True/"
    """Requests Unity to show the task guidance mode collision box to the animal."""
    HIDE_REWARD_ZONE_BOUNDARY = "VisibleMarker/False/"
    """Requests Unity to hide the task guidance mode collision box from the animal."""
    UNITY_SCENE_REQUEST = "SceneNameTrigger/"
    """Requests Unity to send the name of the currently used game scene."""
    UNITY_SCENE = "SceneName/"
    """The topic to which Unity sends the name of the currently used game scene."""


class _MesoscopeVRLogMessageCodes(IntEnum):
    """Defines the set of codes used by the Mesoscope-VR data acquisition to specify the ongoing events when logging
    the system data acquired during runtime.
    """

    SYSTEM_STATE = 1
    """The system has changed its (configuration) state."""
    RUNTIME_STATE = 2
    """The acquired session has changed its (runtime) state."""
    GUIDANCE_STATE = 3
    """The system has changed the VR task guidance state."""
    SHOW_REWARD = 4
    """The system has changed the visibility opf the VR task guidance bounding box."""
    DISTANCE_SNAPSHOT = 5
    """The system has taken a snapshot of the total distance traveled by the animal due to changing the VR wall cue 
    sequence."""


class _MesoscopeVRSystem:
    """Provides methods for conducting data acquisition sessions using the Mesoscope-VR system.

    Notes:
        Calling this initializer does not instantiate all assets required for the runtime. Use the start() method
        before calling other instance methods to properly initialize all required runtime assets and remote
        processes.

        This instance statically reserves the id code '1' to label its log entries.

    Args:
        session_data: The SessionData instance that defines the session for which to acquire the data.
        session_descriptor: The partially configured SessionDescriptor instance that stores the task metadata of the
            session for which to acquire the data.
        experiment_configuration: The MesoscopeExperimentConfiguration instance that specifies the experiment
            configuration to use during the session's data acquisition or None, if the session is not a mesoscope
            experiment session.

    Attributes:
        _mesoscope_frame_delay: The maximum delay, in milliseconds, that can separate the acquisition of any two
            consecutive mesoscope frames, when the mesoscope functions as expected.
        _speed_calculation_window: Determines the window size, in milliseconds, used to calculate the recorded animal's
            running speed.
        _source_id: The unique identifier code of the instance, used to identify the instance in the generated
            data log messages.
        _started: Tracks whether the session's data acquisition has started.
        _terminated: Tracks whether the session's data acquisition has terminated.
        _paused: Tracks whether the session's data acquisition has been temporarily paused.
        _mesoscope_started: Tracks whether the system has started acquiring Mesoscope frames.
        descriptor: The SessionDescriptor instance for the session whose data is acquired by the system during
            runtime.
        _experiment_configuration: The MesoscopeExperimentConfiguration instance for the session whose data is acquired
            by the system during runtime or None, if the session is not of the 'mesoscope experiment' type.
        _system_configuration: The MesoscopeSystemConfiguration instance that defines the configuration of the data
            acquisition system.
        _session_data: The SessionData instance that defines the session whose data is acquired by the system during
            runtime.
        _mesoscope_data: The MesoscopeData instance that defines the filesystem layout of the data acquisition system.
        _system_state: The code that communicates the current Mesoscope-VR system's state.
        _runtime_state: The code that communicates the current data acquisition session's task state (stage).
        _timestamp_timer: The PrecisionTimer instance that timestamps log entries generated by the instance.
        _position: The current absolute position of the animal, in Unity units, relative to the origin of the
            Virtual Reality task environment's track.
        _distance: The total cumulative distance, in centimeters, traveled by the animal since runtime onset.
        _lick_count: The total number of licks performed by the animal since runtime onset.
        _cue_sequence: The sequence of the Virtual Reality environment wall cues used by the session's task
            environment.
        _unconsumed_reward_count: The number of rewards delivered to the animal that has not yet been consumed
            by the animal.
        _enable_guidance: Tracks the state of the session's task guidance mode.
        _show_reward_zone_boundary: Tracks whether the session's task guidance trigger boundary is visible to the
            animal.
        _pause_start_time: The absolute time, in microseconds elapsed since the UTC epoch onset, of the last
            runtime pause onset.
        paused_time: The total time, in seconds, the session's data acquisition runtime spent in the paused
            (idle) state.
        _delivered_water_volume: The total volume of water dispensed by the water delivery valve during the
            active data acquisition state.
        _unity_terminated: Tracks whether the system has detected that the Unity game engine has unexpectedly
            terminated its runtime.
        _mesoscope_frame_count: Tracks the number of frames acquired by the Mesoscope since the last mesoscope frame
            acquisition onset.
        _mesoscope_terminated: Tracks whether the system has detected that the Mesoscope has unexpectedly
            terminated its runtime.
        _running_speed: The animal's running speed, in centimeters per second, computed over the last 50 milliseconds.
        _speed_timer: The PrecisionTimer instance used to compute the animal's running speed in 50-millisecond
            intervals.
        _guided_trials: The remaining number of trials for which to maintain the task guidance mode.
        _failed_trials: The number of consecutive trials for which the animal did not receive a water reward due to
            failing the trial's task.
        _failed_trial_threshold: The number of consecutively failed trials after which the system engages the task
            guidance recovery mode.
        _recovery_trials: The number of trials for which the system engages the task guidance mode when the animal
            repeatedly fails to perform the task.
        _trial_rewarded: Tracks whether the currently executed trial has been rewarded.
        _trial_distances: Stores the total cumulative distance, in centimeters, the animals would travel at the end of
            each trial expected to be executed while acquiring the session's data.
        _trial_rewards: Stores the reward size (volume), in microliters, to be received by the animal for
            successfully completing trials during runtime and the duration, in milliseconds, of the auditory tone
            emitted when delivering each reward.
        _completed_trials: The total number of trials completed by the animal since the last cue sequence
            reset.
        _paused_water_volume: Tracks the total volume of water, in milliliters, dispensed by the water delivery valve
            when the session's data acquisition was paused.
        _logger: The DataLogger instance that logs the data from all sources managed by the Mesoscope-VR instance.
        _microcontrollers: The MicroControllerInterfaces instance that interfaces with the Actor, Sensor, and Encoder
            microcontrollers used during runtime.
        _cameras: The VideoSystems instance that interfaces with the face and body cameras used during runtime.
        _zaber_motors: The ZaberMotors instance that interfaces with the HeadBar, LickPort, and Wheel motor groups.
        _unity: The MQTTCommunication instance that bidirectionally transfers data between this instance and the Unity
            game engine managing the session's Virtual Reality task environment.
        _ui: The RuntimeControlUI instance that maintains a Graphical User Interface that allows the user to
            control the session's runtime.
        _visualizer: The BehaviorVisualizer instance used during runtime to visualize the animal's behavior or
            None, if the managed runtime does not require behavior visualization.
        _mesoscope_timer: The PrecisionTimer instance used to track the delay between receiving consecutive
            mesoscope frame acquisition pulses.
        _motif_decomposer: The MotifDecomposer instance used during runtime to decompose long VR cue sequences
            into the sequence of trials and corresponding cumulative traveled distances associated with each trial.

    Raises:
        RuntimeError: If the host-machine does not have enough logical CPU cores to support the runtime.
    """

    # Statically assigns mesoscope frame checking window and speed calculation window, in milliseconds.
    _mesoscope_frame_delay: int = 300
    _speed_calculation_window: int = 50

    # Reserves logging source ID code 1 for this class
    _source_id: np.uint8 = np.uint8(1)

    def __init__(
        self,
        session_data: SessionData,
        session_descriptor: MesoscopeExperimentDescriptor | LickTrainingDescriptor | RunTrainingDescriptor,
        experiment_configuration: MesoscopeExperimentConfiguration | None = None,
    ) -> None:
        # Creates runtime state tracking flags
        self._started: bool = False
        self._terminated: bool = False
        self._paused: bool = False
        self._mesoscope_started: bool = False

        # Pre-runtime check to ensure that the host-machine has enough cores to facilitate the data acquisition.
        # 3 cores for microcontrollers, 1 core for the data logger, 4 cores for the video systems
        # (2 producers, 2 consumers), 1 core for the central process calling this method, 1 core for
        # the main GUI: 10 cores total.
        cpu_count = os.cpu_count()
        if cpu_count is None or not cpu_count >= 10:
            message = (
                f"Unable to initialize the Mesoscope-VR system runtime control class. The host PC must have at least "
                f"10 logical CPU cores available for this runtime to work as expected, but only {cpu_count} cores are "
                f"available."
            )
            console.error(message=message, error=RuntimeError)

        # Caches SessionDescriptor and MesoscopeExperimentConfiguration instances to class attributes.
        self.descriptor: MesoscopeExperimentDescriptor | LickTrainingDescriptor | RunTrainingDescriptor = (
            session_descriptor
        )
        self._experiment_configuration: MesoscopeExperimentConfiguration | None = experiment_configuration

        # Caches the descriptor to disk. Primarily, this is required for preprocessing the data if the session's runtime
        # terminates unexpectedly.
        self.descriptor.to_yaml(file_path=session_data.raw_data.session_descriptor_path)

        # Resolves and caches the Mesoscope-VR and the processed session's configuration parameters.
        self._system_configuration: MesoscopeSystemConfiguration = get_system_configuration()
        self._session_data: SessionData = session_data
        self._mesoscope_data: MesoscopeData = MesoscopeData(
            session_data=session_data, system_configuration=self._system_configuration
        )

        # Generates a precursor MesoscopePositions file and dumps it to the session's raw_data directory.
        # If a previous set of mesoscope position coordinates is available, overwrites the 'default' mesoscope
        # coordinates with the positions loaded from the snapshot stored inside the persistent_data directory of the
        # animal.
        if self._mesoscope_data.vrpc_data.mesoscope_positions_path.exists():
            # Loading and re-dumping the data updates the contents of the position's file to dynamically integrate any
            # upstream changes in the sl-shared-assets into the file structure.
            previous_mesoscope_positions: MesoscopePositions = MesoscopePositions.from_yaml(
                file_path=self._mesoscope_data.vrpc_data.mesoscope_positions_path
            )
            previous_mesoscope_positions.to_yaml(file_path=session_data.raw_data.mesoscope_positions_path)

        # If previous position data is not available, creates a new MesoscopePositions instance with default position
        # values.
        else:
            # Caches the precursor file to the raw_data session directory and to the persistent data directory.
            precursor = MesoscopePositions()
            precursor.to_yaml(file_path=session_data.raw_data.mesoscope_positions_path)
            precursor.to_yaml(file_path=self._mesoscope_data.vrpc_data.mesoscope_positions_path)

        # Defines the asset used to set and maintain combinations of system and runtime (task) states.
        self._system_state: int = 0
        self._runtime_state: int = 0
        self._timestamp_timer: PrecisionTimer = PrecisionTimer(precision=TimerPrecisions.MICROSECOND)

        # Initializes the tracker attributes used to cyclically handle data updates during runtime.
        self._position: np.float64 = np.float64(0.0)
        self._distance: np.float64 = np.float64(0.0)
        self._lick_count: np.uint64 = np.uint64(0)
        self._cue_sequence: NDArray[np.uint8] = np.zeros(shape=(0,), dtype=np.uint8)
        self._unconsumed_reward_count: int = 0
        self._enable_guidance: bool = False
        self._show_reward_zone_boundary: bool = False
        self._pause_start_time: int = 0
        self.paused_time: int = 0
        self._delivered_water_volume: np.float64 = np.float64(0.0)
        self._unity_terminated: bool = False
        self._mesoscope_frame_count: np.uint64 = np.uint64(0)
        self._mesoscope_terminated: bool = False
        self._running_speed: np.float64 = np.float64(0.0)
        self._speed_timer = PrecisionTimer(precision=TimerPrecisions.MILLISECOND)
        self._guided_trials: int = 0
        self._failed_trials: int = 0
        self._failed_trial_threshold: int = 0
        self._recovery_trials: int = 0
        self._trial_rewarded: bool = False
        self._trial_distances: NDArray[np.float64] = np.zeros(shape=(0,), dtype=np.float64)
        self._trial_rewards: tuple[tuple[float, int], ...] = ((0.0, 0),)
        self._completed_trials: int = 0
        self._paused_water_volume: np.float64 = np.float64(0.0)

        # Initializes the DataLogger instance used to log data from all microcontrollers, camera frame savers, and this
        # class instance.
        self._logger: DataLogger = DataLogger(
            output_directory=session_data.raw_data.raw_data_path,
            instance_name="behavior",  # Creates behavior_log subdirectory under raw_data
            thread_count=10,
        )

        # Initializes the binding class for all MicroController Interfaces.
        self._microcontrollers: MicroControllerInterfaces = MicroControllerInterfaces(
            data_logger=self._logger, microcontroller_configuration=self._system_configuration.microcontrollers
        )

        # Initializes the binding class for all VideoSystems.
        self._cameras: VideoSystems = VideoSystems(
            data_logger=self._logger,
            output_directory=self._session_data.raw_data.camera_data_path,
            camera_configuration=self._system_configuration.cameras,
        )

        # The ZaberLauncher UI cannot connect to the ports managed by Python bindings, so it must be initialized before
        # connecting to motor groups from Python.
        message = (
            "Preparing to connect to all managed Zaber motors. Make sure that the ZaberLauncher app is running before "
            "proceeding further. If the ZaberLauncher is not running, it will be IMPOSSIBLE to manually control the "
            "Zaber motors."
        )
        console.echo(message=message, level=LogLevel.WARNING)
        _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
        input("Enter anything to continue: ")

        # If the system has a snapshot of the Zaber positions used during a previous runtime, loads it into memory and
        # restores all Zaber motors to that snapshot. Otherwise, uses predefined default positions and expects the
        # user to fine-tune them as necessary.
        if self._mesoscope_data.vrpc_data.zaber_positions_path.exists():
            zaber_positions = ZaberPositions.from_yaml(file_path=self._mesoscope_data.vrpc_data.zaber_positions_path)
        else:
            zaber_positions = None

        # Initializes the binding class for all Zaber motors.
        self._zaber_motors: ZaberMotors = ZaberMotors(
            zaber_positions=zaber_positions, zaber_configuration=self._system_configuration.assets
        )

        # Defines optional assets used by some, but not all runtimes. Most of these assets are initialized to None by
        # default and are overwritten by the start() method.
        self._unity: MQTTCommunication | None = None
        self._mesoscope_timer: PrecisionTimer | None = None
        self._motif_decomposer = CachedMotifDecomposer()  # Only used by experiment sessions.

        # Initializes but does not start the assets used by all runtimes. These assets need to be started in a
        # specific order, which is handled by the start() method.
        self._ui: RuntimeControlUI = RuntimeControlUI()
        self._visualizer: BehaviorVisualizer = BehaviorVisualizer()

    def start(self) -> None:
        """Guides the user through a semi-interactive sequence of seps that prepares the assets used to acquire the
        session's data.

        Notes:
            This method executes a complex initialization sequence that initializes and configures all assets, internal
            (managed by the VRPC) and external (managed by other PCs and / or software) and often takes a significant
            amount of time.

            As part of its runtime, the method gradually reserves an expanding pool of host-machine's resources (CPUs,
            GPUs, memory, etc.) to support the runtime of the initialized assets.
        """
        # If the assets are already initialized, aborts the runtime early.
        if self._started:
            return

        message = "Initializing Mesoscope-VR system assets..."
        console.echo(message=message, level=LogLevel.INFO)

        # Starts the data logger
        self._logger.start()

        # Generates and logs the onset timestamp for the Mesoscope-VR system.
        onset: NDArray[np.uint8] = get_timestamp(output_format=TimestampFormats.BYTES)
        self._timestamp_timer.reset()  # Immediately resets the timer to align it with the onset timestamp.
        self._logger.input_queue.put(
            LogPackage(source_id=self._source_id, acquisition_time=np.uint64(0), serialized_data=onset)
        )  # Logs the onset timestamp

        message = "DataLogger: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

        # Starts all microcontroller interfaces
        self._microcontrollers.start()

        # Sets the runtime into the Idle state before instructing the user to finalize runtime preparations.
        self.idle()

        # Generates a snapshot of the runtime hardware configuration. In turn, this data is used to parse the .npz log
        # files during processing.
        self._generate_hardware_state_snapshot()

        # If the session uses Virtual Reality, initializes the MQTT communication with the Unity game engine.
        if self._session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
            monitored_topics = (
                _MesoscopeVRMQTTTopics.CUE_SEQUENCE,
                _MesoscopeVRMQTTTopics.UNITY_TERMINATION,
                _MesoscopeVRMQTTTopics.UNITY_STARTUP,
                _MesoscopeVRMQTTTopics.UNITY_SCENE,
                self._microcontrollers.valve.mqtt_topic,
            )
            self._unity = MQTTCommunication(monitored_topics=monitored_topics)
            self._unity.connect()  # Establishes communication with the MQTT broker.

            # Guides the user through the Unity setup sequence.
            self._setup_unity()

            # Configures the VR task to match the initial GUI state
            self._enable_guidance = self._ui.enable_guidance
            self._show_reward_zone_boundary = self._ui.show_reward
            self._toggle_lick_guidance(enable_guidance=self._enable_guidance)
            self._toggle_show_reward(show_reward=self._show_reward_zone_boundary)

        # Begins acquiring and displaying frames with the all available cameras.
        self._cameras.start_face_camera()
        self._cameras.start_body_camera()

        # If necessary, carries out the Zaber motor setup and animal mounting sequence and generates a snapshot of all
        # zaber motor positions. This serves as an early checkpoint in case the runtime has to be aborted in a
        # non-graceful way (without running the stop() sequence). This way, the next runtime restarts with the
        # calibrated zaber positions. The snapshot includes any adjustment to the HeadBar positions performed during
        # the red-dot alignment.
        _setup_zaber_motors(zaber_motors=self._zaber_motors)
        _generate_zaber_snapshot(
            session_data=self._session_data, mesoscope_data=self._mesoscope_data, zaber_motors=self._zaber_motors
        )

        # Saves the MesoscopeExperimentConfiguration instance to the session directory if the managed runtime is an
        # experiment session
        if self._experiment_configuration is not None:
            self._experiment_configuration.to_yaml(self._session_data.raw_data.experiment_configuration_path)
            message = "Experiment configuration snapshot: Generated."
            console.echo(message=message, level=LogLevel.SUCCESS)

        # If the session is a mesoscope experiment, initializes the mesoscope and saves the experiment configuration
        # snapshot to the session's raw-data directory.
        if self._session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
            # Caches the experiment configuration to the session's raw_data directory.
            if self._experiment_configuration is not None:
                self._experiment_configuration.to_yaml(self._session_data.raw_data.experiment_configuration_path)
                message = "Experiment configuration snapshot: Generated."
                console.echo(message=message, level=LogLevel.SUCCESS)

            # Instructs the user to prepare the mesoscope for data acquisition.
            _setup_mesoscope(session_data=self._session_data, mesoscope_data=self._mesoscope_data)

            # Initializes the milliseconds-precise timer used to track the delay between consecutive mesoscope
            # frame pulses.
            self._mesoscope_timer = PrecisionTimer(precision=TimerPrecisions.MILLISECOND)

        # Initializes the runtime control GUI.
        self._ui.start()

        # Initializes the runtime visualizer. This HAS to be initialized after cameras and the UI to prevent collisions
        # in the QT backend, which is used by all three assets.
        self._visualizer.open()

        # Enters the manual checkpoint loop. This loop holds the runtime and allows using the GUI to test all runtime
        # components before starting the data acquisition.
        self._checkpoint()

        # If the user chooses to abort (terminate) the runtime during checkpoint, aborts the method runtime early.
        if self._terminated:
            # Sets the flag to True to support the proper stop() method runtime.
            self._started = True
            return

        message = "Initiating data acquisition..."
        console.echo(message=message, level=LogLevel.INFO)

        # Starts saving frames from al cameras
        self._cameras.save_face_camera_frames()
        self._cameras.save_body_camera_frames()

        # Starts mesoscope frame acquisition if the runtime is a mesoscope experiment.
        if self._session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
            # Enables mesoscope frame monitoring
            self._microcontrollers.mesoscope_frame.set_monitoring_state(state=True)

            # Ensures that the frame monitoring starts before acquisition.
            _response_delay_timer.delay(delay=1000, block=False)  # Uses the global response delay timer.

            # Starts acquiring mesoscope frames.
            self._start_mesoscope()

        # The setup procedure is complete.
        self._started = True

        message = "Mesoscope-VR system: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def stop(self) -> None:
        """Stops and terminates all Mesoscope-VR system components, external assets, and ends the runtime.

        This method releases the hardware resources used during runtime by various system components by triggering
        appropriate graceful shutdown procedures for all components. Then, it generates a set of files that store
        various runtime metadata. Finally, it calls the data preprocessing pipeline to efficiently package the data and
        safely transfer it to the long-term storage destinations.
        """
        # Prevents stopping an already stopped process.
        if not self._started:
            return

        # Resets the _started tracker before attempting the shutdown sequence
        self._started = False

        message = "Terminating Mesoscope-VR system runtime..."
        console.echo(message=message, level=LogLevel.INFO)

        # Switches the system into the IDLE state. Since IDLE state has most modules set to stop-friendly states,
        # this is used as a shortcut to prepare the VR system for shutdown. Also, this clearly marks the end of the
        # main runtime period.
        self.idle()

        # Shuts down the UI and the visualizer
        self._ui.shutdown()
        self._visualizer.close()

        # Disconnects from the MQTT broker that facilitates communication with Unity.
        if self._unity is not None:
            self._unity.disconnect()

        # Stops all cameras.
        self._cameras.stop()

        # Stops mesoscope frame acquisition and monitoring if the runtime uses Mesoscope.
        if self._session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT and self._mesoscope_started:
            self._stop_mesoscope()
            self._microcontrollers.mesoscope_frame.set_monitoring_state(state=False)

            # Renames the mesoscope data directory to include the session name. This both clears the shared directory
            # for the next acquisition and ensures that the mesoscope data collected during runtime will be preserved
            # unless it is preprocessed or the user removes it manually.
            rename_mesoscope_directory(session_data=self._session_data)

        # Updates the internally stored SessionDescriptor instance with runtime data, saves it to disk, and instructs
        # the user to add experimenter notes and other user-defined information to the descriptor file.
        self._generate_session_descriptor()

        # For Mesoscope experiment runtimes, generates the snapshot of the current mesoscope objective position. This
        # has to be done before the objective is lifted to remove the animal from the Mesoscope enclosure. This data
        # is reused during the following experiment session to restore the imaging field to the same state as during
        # this session.
        if self._session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
            _generate_mesoscope_position_snapshot(session_data=self._session_data, mesoscope_data=self._mesoscope_data)

        # Generates the snapshot of the current Zaber motor positions and saves them as a .yaml file. This has
        # to be done before Zaber motors are potentially reset back to parking position. Skips generation of the
        # zaber snapshot if the runtime terminated before motors were restored to the previous day's imaging
        # position.
        _generate_zaber_snapshot(
            session_data=self._session_data, mesoscope_data=self._mesoscope_data, zaber_motors=self._zaber_motors
        )

        # Optionally resets Zaber motors by moving them to the dedicated parking position before shutting down Zaber
        # connection. Regardless of whether the motors are moved, disconnects from the motors at the end of method
        # runtime.
        _reset_zaber_motors(zaber_motors=self._zaber_motors)

        # Microcontroller and data-logger stopping was moved to the end of the shutdown sequence to avoid an extremely
        # rare issue related to one of the microcontrollers deadlocking internally. The idle() state combined with the
        # mesoscope stop sequence should cut all microcontroller data streams, so there is no urgency in actually
        # terminating these assets before the animal is safely removed from the Mesoscope enclosure. Conversely, if
        # microcontrollers cannot be stopped and the user has to perform a hard shutdown, having this done after
        # resolving session metadata ensures that the user can manually call preprocessing as soon as the runtime is
        # terminated.

        # Stops all microcontroller interfaces
        self._microcontrollers.stop()

        # Stops the data logger instance
        self._logger.stop()

        message = "Data Logger: Stopped."
        console.echo(message=message, level=LogLevel.SUCCESS)

        # Cleans up all SharedMemoryArray objects and leftover references before entering data processing mode to
        # support parallel runtime preparations.
        del self._microcontrollers
        del self._zaber_motors
        del self._cameras
        del self._logger

        # Notifies the user that the acquisition is complete.
        console.echo(message="Data acquisition: Complete.", level=LogLevel.SUCCESS)

        # If the session was not fully initialized, skips the preprocessing. The main runtime logic function will
        # automatically execute 'failed session data purging' runtime based on the presence of the marker.
        if self._session_data.raw_data.nk_path.exists():
            return

        # Determines whether to carry out data preprocessing or purging.
        message = (
            "Do you want to carry out data preprocessing or purge the data? CRITICAL! Only enter 'purge session' if "
            "you want to permanently DELETE the session data. All valid data REQUIRES preprocessing to ensure safe "
            "storage."
        )
        console.echo(message=message, level=LogLevel.WARNING)
        while True:
            answer = input("Enter 'yes', 'no' or 'purge session': ")

            # Default case: preprocesses the data. For experiment runtimes, this may take between 15 and 20 minutes.
            if answer.lower() == "yes":
                preprocess_session_data(session_data=self._session_data)
                break

            # Does not carry out data preprocessing or purging. In certain scenarios, it may be necessary to skip data
            # preprocessing in favor of faster animal turnover. Although highly discouraged, this is nonetheless a valid
            # runtime termination option.
            if answer.lower() == "no":
                break

            # Exclusively for failed runtimes: removes all session data from all destinations.
            if answer.lower() == "purge session":
                purge_session(session_data=self._session_data)
                break

        message = "Mesoscope-VR system runtime: Terminated."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def _generate_hardware_state_snapshot(self) -> None:
        """Resolves and caches the snapshot of the system's hardware configuration parameters to the acquired session's
        raw_data directory as a hardware_state.yaml file.
        """
        if self._session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT and self._experiment_configuration:
            hardware_state = MesoscopeHardwareState(
                cm_per_pulse=float(self._microcontrollers.wheel_encoder.cm_per_pulse),
                maximum_brake_strength=float(self._microcontrollers.brake.maximum_brake_strength),
                minimum_brake_strength=float(self._microcontrollers.brake.minimum_brake_strength),
                lick_threshold=int(self._microcontrollers.lick.lick_threshold),
                valve_scale_coefficient=float(self._microcontrollers.valve.scale_coefficient),
                valve_nonlinearity_exponent=float(self._microcontrollers.valve.nonlinearity_exponent),
                torque_per_adc_unit=float(self._microcontrollers.torque.torque_per_adc_unit),
                screens_initially_on=self._microcontrollers.screens.initially_on,
                recorded_mesoscope_ttl=True,
                system_state_codes=_MesoscopeVRStates.to_dict(),
            )
        # Note, lick and run training runtimes only use a subset of all hardware modules.
        elif self._session_data.session_type == SessionTypes.LICK_TRAINING:
            hardware_state = MesoscopeHardwareState(
                torque_per_adc_unit=float(self._microcontrollers.torque.torque_per_adc_unit),
                lick_threshold=int(self._microcontrollers.lick.lick_threshold),
                valve_scale_coefficient=float(self._microcontrollers.valve.scale_coefficient),
                valve_nonlinearity_exponent=float(self._microcontrollers.valve.nonlinearity_exponent),
                system_state_codes=_MesoscopeVRStates.to_dict(),
            )
        elif self._session_data.session_type == SessionTypes.RUN_TRAINING:
            hardware_state = MesoscopeHardwareState(
                cm_per_pulse=float(self._microcontrollers.wheel_encoder.cm_per_pulse),
                lick_threshold=int(self._microcontrollers.lick.lick_threshold),
                valve_scale_coefficient=float(self._microcontrollers.valve.scale_coefficient),
                valve_nonlinearity_exponent=float(self._microcontrollers.valve.nonlinearity_exponent),
                system_state_codes=_MesoscopeVRStates.to_dict(),
            )
        else:
            # It should be impossible to satisfy this error clause, but is kept for safety reasons
            message = (
                f"Unsupported session type {self._session_data.session_type} encountered when generating "
                f"the snapshot of the Mesoscope-VR system's hardware configuration."
            )
            console.error(message=message, error=ValueError)
            # A fall-back to appease mypy, should not be reachable
            raise ValueError(message)  # pragma: no cover

        # Caches the resolved hardware state to disk
        hardware_state.to_yaml(self._session_data.raw_data.hardware_state_path)
        message = "Mesoscope-VR hardware configuration snapshot: Generated."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def _generate_session_descriptor(self) -> None:
        """Updates the contents of the locally stored session descriptor file with runtime data and caches it to
         the session's raw_data directory.

        This utility method is used as part of the stop() method runtime to generate the session_descriptor.yaml file.
        Since this file combines both runtime-generated and user-generated data, this method also ensures that the
        user updates the descriptor file to include experimenter notes taken during runtime.
        """
        # The presence of the 'nk.bin' marker indicates that the session has not been properly initialized. Since
        # this method can be called as part of the emergency shutdown process for a session that encountered an
        # initialization error, if the marker exists, ends the runtime early.
        if self._session_data.raw_data.nk_path.exists():
            return

        # Updates the contents of the pregenerated descriptor file and dumps it as a .yaml into the root raw_data
        # session directory. This needs to be done after the microcontrollers and loggers have been stopped to ensure
        # that the reported water volumes are accurate:

        # Runtime water volume. This should accurately reflect the volume of water consumed by the animal during
        # runtime.
        delivered_water = self._microcontrollers.valve.delivered_volume - self._paused_water_volume
        # Converts from uL to ml
        self.descriptor.dispensed_water_volume_ml = float(round(delivered_water / 1000, ndigits=3))

        # Same as above, but tracks the total volume of water dispensed during pauses. While the animal might
        # have consumed some of that water, it is equally plausible that all water was wasted or not dispensed at all.
        self.descriptor.pause_dispensed_water_volume_ml = float(round(self._paused_water_volume / 1000, ndigits=3))
        self.descriptor.incomplete = False  # If the runtime reaches this point, the session is likely complete.

        # Precalculates the volume of water that the experimenter needs to deliver to the animal if the combined
        # volume delivered during runtime and paused state is less than 1 ml. This is used to pre-fill the
        # experimenter-delivered volume field as a convenience feature for experimenters.
        total_delivered_volume = (
            self.descriptor.dispensed_water_volume_ml + self.descriptor.pause_dispensed_water_volume_ml
        )
        if total_delivered_volume < 1:
            self.descriptor.experimenter_given_water_volume_ml = float(round(1 - total_delivered_volume, ndigits=3))

        # Ensures that the user updates the descriptor file.
        _verify_descriptor_update(
            descriptor=self.descriptor, session_data=self._session_data, mesoscope_data=self._mesoscope_data
        )

    def _setup_unity(self) -> None:
        """Guides the user through the setup sequence for the Unity game engine and the session's Virtual Reality
        task environment.
        """
        # If the runtime does not use Unity, aborts the runtime early.
        if self._unity is None:
            return

        # Activates the VR screens so that the user can check whether the Unity task displays as expected.
        self._microcontrollers.screens.set_state(state=True)

        # Delays the runtime for 2 seconds to ensure that the VR screen controllers receive the activation pulse and
        # activate the screens before prompting the user to cycle Unity task states.
        _response_delay_timer.delay(delay=2000, block=False)

        # Discards all data received from Unity up to this point to reset the queue for the verification step below.
        while self._unity.has_data:
            _ = self._unity.get_data()

        # Instructs the user to check the displays.
        message = (
            "Start Unity game engine and load the session's Virtual Reality scene (task). Start the scene (hit the "
            "'play' button) to advance to the next verification stage."
        )
        console.echo(message=message, level=LogLevel.INFO)

        # Blocks until Unity sends the task termination message.
        while True:
            # Parses all data received from the Unity game engine.
            if not self._unity.has_data:
                continue
            topic: str
            topic, _ = self._unity.get_data()

            # If received data is a startup message, breaks the loop
            if topic == _MesoscopeVRMQTTTopics.UNITY_STARTUP:
                break

        # Verifies that the Unity scene (VR task) started by the user matches the task declared in the experiment
        # configuration file.
        while not self._verify_unity_task():
            input("Enter anything to retry: ")

        # Guides the user through the verification process and ensures that Unity is cycled off at the end of the
        # verification process
        message = (
            "Verify that the Virtual Reality scene displays on the VR screens as intended. Disable (end) Unity "
            "runtime to advance to the next preparation step."
        )
        console.echo(message=message, level=LogLevel.INFO)

        while True:
            _response_delay_timer.delay(delay=100, block=False)  # Prevents the motion from being too fast

            # Advances the Unity scene forward by 0.1 Unity unit (~ 10 mm)
            json_string = dumps(obj={"movement": 0.1})
            byte_array = json_string.encode("utf-8")
            self._unity.send_data(topic=self._microcontrollers.wheel_encoder.mqtt_topic, payload=byte_array)

            # Parses the incoming data sent from the Unity game engine.
            if not self._unity.has_data:
                continue
            topic, _ = self._unity.get_data()

            # If the received data is a termination message, asks the user if the loop needs to be broken
            if topic != _MesoscopeVRMQTTTopics.UNITY_TERMINATION:
                continue

            message = "Unity termination: Detected. Do you want to end the Unity verification runtime?"
            _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)
            console.echo(message=message, level=LogLevel.INFO)

            # Requests the user to provide a valid answer.
            answer = ""
            while answer not in {"y", "n"}:
                answer = input("Enter 'yes' or 'no': ").lower()[0]

            # Breaks the verification loop if the user confirms they want to break the loop.
            if answer == "y":
                break

            # Otherwise, if the answer is 'n', notifies the user that they are still in the verification loop.
            message = "Continuing sending the motion triggers until the next Unity termination event..."
            console.echo(message=message, level=LogLevel.INFO)

        # Instructs the user to restart the task (re-arm Unity).
        message = (
            "Arm the Unity task by hitting the 'play' button in Unity. Keep the task armed for the rest of the "
            "session's data acquisition runtime. It may be necessary to terminate and re-arm the task for the trigger "
            "to be detected."
        )
        console.echo(message=message, level=LogLevel.INFO)

        # Blocks until Unity sends another start message. Since at this point the Unity-VRPC connection is known to
        # be working, it does not use timeout or abort logic.
        while True:
            if not self._unity.has_data:
                continue
            topic, _ = self._unity.get_data()
            if topic == _MesoscopeVRMQTTTopics.UNITY_STARTUP:
                break

        # Disables the VR screens before returning.
        self._microcontrollers.screens.set_state(state=False)

        # Requests and resolves the Virtual Reality cue sequence for the current VR task.
        self._get_cue_sequence()

        message = "Unity setup: Complete."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def _verify_unity_task(self) -> bool | None:
        """Ensures that the Unity game engine is configured to display the Virtual Reality task scene expected by the
        acquired session.

        Returns:
            True if the Unity game engine is configured to display the correct VR task scene, False otherwise.
            None, if the session does not use Unity or is not an experiment session.
        """
        # Aborts the runtime early if the session does not use Unity or is not an experiment session.
        if self._unity is None or self._experiment_configuration is None:
            return None

        message = "Verifying that the Unity game engine is configured to display the correct scene..."
        console.echo(message=message, level=LogLevel.INFO)

        # Discards all data received from Unity up to this point before entering the scene name verification runtime.
        while self._unity.has_data:
            _ = self._unity.get_data()

        # Sends a request for the scene (task) name to Unity GIMBL package.
        self._unity.send_data(topic=_MesoscopeVRMQTTTopics.UNITY_SCENE_REQUEST)
        _response_delay_timer.reset()  # Co-opts the global delay timer for this method.

        # Blocks until Unity sends the active task scene name.
        while True:
            # Continuously requests the scene name at 5-second intervals.
            if _response_delay_timer.elapsed > 5000:
                self._unity.send_data(topic=_MesoscopeVRMQTTTopics.UNITY_SCENE_REQUEST)

            # Parses all data received from the Unity game engine.
            if not self._unity.has_data:
                continue

            topic: str
            topic, payload = self._unity.get_data()

            # Discards all messages other than the Unity scene name messages.
            if topic != _MesoscopeVRMQTTTopics.UNITY_SCENE:
                continue

            # Extracts the name of the scene running in Unity.
            scene_name: str = json.loads(payload.decode("utf-8"))["name"]
            expected_scene_name: str = self._experiment_configuration.unity_scene_name

            if scene_name == expected_scene_name:
                # If the scene name matches the expected name, returns True.
                message = "Unity scene configuration: Confirmed."
                console.echo(message=message, level=LogLevel.SUCCESS)
                return True

            # Otherwise, displays an error message and returns False.
            message = (
                f"The name of the Virtual Reality scene (task) running in Unity ({scene_name}) does not match the "
                f"scene name expected based on the session's experiment configuration ({expected_scene_name}). "
                f"Reconfigure Unity to run the correct VR task and try again."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            return False

    def _get_cue_sequence(self) -> None:
        """Queries the sequence of virtual reality environment's wall cues for the session's task running in Unity.

        Raises:
            RuntimeError: If the Unity does not respond to the cue sequence request within 10 seconds.
        """
        # Aborts the runtime early if the session does not use Unity.
        if self._unity is None:
            return

        # Discards all data received from Unity up to this point.
        while self._unity.has_data:
            _ = self._unity.get_data()

        # Requests Unity to transmit the currently used task cue sequence
        self._unity.send_data(topic=_MesoscopeVRMQTTTopics.CUE_SEQUENCE_REQUEST)

        # Resets the global delay timer to time the cue sequence reception loop.
        _response_delay_timer.reset()

        # Ensures that the request loop is kept for at most 10 seconds
        while _response_delay_timer.elapsed < 10000:
            # Repeatedly queries and checks incoming messages from Unity.
            if not self._unity.has_data:
                continue
            topic: str
            payload: bytes
            topic, payload = self._unity.get_data()

            # If the message contains cue sequence data, parses it and finishes method runtime. Discards all
            # other messages.
            if topic != _MesoscopeVRMQTTTopics.CUE_SEQUENCE:
                continue

            # Extracts the runtime cue sequence into the instance's attribute.
            self._cue_sequence = np.array(json.loads(payload.decode("utf-8"))["cue_sequence"], dtype=np.uint8)

            # Logs the received sequence.
            self._logger.input_queue.put(
                LogPackage(
                    source_id=self._source_id,
                    acquisition_time=np.uint64(self._timestamp_timer.elapsed),
                    serialized_data=self._cue_sequence,
                )
            )

            # Decomposes the received cue sequence into a sequence of trials and resolves additional metadata necessary
            # to support the session's task execution.
            self._decompose_cue_sequence_into_trials()

            # Resets the traveled distance tracker array and internal class attributes used for position, running speed,
            # and trial completion tracking.
            self._microcontrollers.wheel_encoder.reset_distance_tracker()
            self._position = np.float64(0.0)
            self._distance = np.float64(0.0)
            self._completed_trials = 0

            # Ends the runtime
            message = "VR cue sequence: Received."
            console.echo(message=message, level=LogLevel.SUCCESS)
            return

        # If the loop above is escaped, this is due to not receiving any message from Unity. Raises an error.
        message = (
            f"The Mesoscope-VR system has requested the Virtual task wall cue sequence by sending the trigger to "
            f"the {_MesoscopeVRMQTTTopics.CUE_SEQUENCE_REQUEST}' topic and received no response in 10 seconds. It is "
            f"likely that the Unity game engine is not running or is not configured to work with the Mesoscope-VR "
            f"data acquisition system."
        )
        console.error(message=message, error=RuntimeError)

    def _decompose_cue_sequence_into_trials(self) -> None:
        """Decomposes the Virtual Reality environment's cue sequence into a sequence of trials.

        Notes:
            Uses a greedy longest-match approach to identify trial motifs in the processed cue sequence.

        Raises:
            RuntimeError: If the method is not able to fully decompose the Virtual Reality environment cue sequence into
                a sequence of trials.
        """
        # If the session is not an experiment session, aborts the runtime early.
        if self._experiment_configuration is None:
            return

        # Extracts the types of trials supported by the acquired session.
        trials: list[MesoscopeExperimentTrial] = [
            trial for trial in self._experiment_configuration.trial_structures.values()
        ]

        # Extracts trial motifs (cue sequences for each trial type) and their corresponding distances in cm.
        trial_motifs: list[NDArray[np.uint8]] = [np.array(trial.cue_sequence, dtype=np.uint8) for trial in trials]
        trial_distances: list[float] = [float(trial.trial_length_cm) for trial in trials]

        # Prepares the flattened motif data using the MotifDecomposer class.
        motifs_flat, motif_starts, motif_lengths, motif_indices, distances_array = (
            self._motif_decomposer.prepare_motif_data(trial_motifs, trial_distances)
        )

        # Estimates the maximum number of trials that can be theoretically extracted from the input cue sequence. This
        # is primarily a safety feature designed to abort the decomposition process if it runs for too long.
        min_motif_length = min(len(motif) for motif in trial_motifs)
        max_trials = len(self._cue_sequence) // min_motif_length + 1

        # CallS Numba-accelerated worker method to decompose the sequence.
        trial_indices_array, trial_count = self._decompose_sequence_numba_flat(
            self._cue_sequence, motifs_flat, motif_starts, motif_lengths, motif_indices, max_trials
        )

        # Checks for decomposition errors
        if trial_count == -1:
            # Finds the position where decomposition failed to construct an informative error message.
            sequence_pos = 0
            trial_indices_list = trial_indices_array[:max_trials].tolist()

            # Reconstructs the position at which the decomposition failed by summing the lengths of successfully
            # matched trials.
            for idx in trial_indices_list:
                if idx == 0 and sequence_pos > 0:  # Assumes 0 is not a valid trial index after the first match
                    break
                sequence_pos += len(trial_motifs[idx])

            remaining_sequence = self._cue_sequence[sequence_pos : sequence_pos + 20]
            message = (
                f"Unable to decompose the acquired session's Virtual Reality environment's cue sequence into a "
                f"sequence of trials. No trial motif matched the processed sequence at the overall sequence position "
                f"{sequence_pos}. The last 20 cues that were not matches to any motif: {remaining_sequence.tolist()}."
            )
            console.error(message=message, error=RuntimeError)
            return

        # Uses the decomposed trial sequence to construct an array of cumulative distances and a tuple of reward sizes
        # and tone durations for each trial.
        trial_indices_list = trial_indices_array[:trial_count].tolist()
        trial_distance_array: NDArray[np.float64] = np.array(
            [distances_array[trial_type] for trial_type in trial_indices_list], dtype=np.float64
        )
        self._trial_distances = np.cumsum(trial_distance_array, dtype=np.float64)
        self._trial_rewards = tuple(
            [(float(trial.trial_reward_size_ul), int(trial.reward_tone_duration_ms)) for trial in trials]
        )

    @staticmethod
    @njit(cache=True)
    def _decompose_sequence_numba_flat(
        cue_sequence: NDArray[np.uint8],
        motifs_flat: NDArray[np.uint8],
        motif_starts: NDArray[np.int32],
        motif_lengths: NDArray[np.int32],
        motif_indices: NDArray[np.int32],
        max_trials: int,
    ) -> tuple[NDArray[np.int32], int]:
        """Decomposes a long sequence of Virtual Reality (VR) wall cues into individual trial motifs.

        Notes:
            This worker function is used to speed up decomposition via numba-acceleration.

        Args:
            cue_sequence: The full Virtual Reality environment cue sequence to decompose.
            motifs_flat: All trial type motifs supported by the acquired session, concatenated into a single 1D array.
            motif_starts: The starting index of each unique motif in the motifs_flat array.
            motif_lengths: The length of each motif unique motif in the motifs_flat array.
            motif_indices: Stores the original trial type motif indices before they are sorted to optimize the lookup
                speed.
            max_trials: The maximum number of trials that can make up the entire cue sequence.

        Returns:
            A tuple of two elements. The first element is the array of trials (trial-type indices) decoded from the
            cue sequence. The second element is the total number of trials extracted from the cue sequence.
        """
        # Prepares runtime trackers
        trial_indices = np.zeros(max_trials, dtype=np.int32)
        trial_count = 0
        sequence_pos = 0
        sequence_length = len(cue_sequence)
        num_motifs = len(motif_lengths)

        # Decomposes the sequence into trial motifs using greedy matching. Longer motifs are matched over shorter ones.
        # Pre-specifying the maximum number of trials serves as a safety feature to avoid processing errors.
        while sequence_pos < sequence_length and trial_count < max_trials:
            motif_found = False

            for i in range(num_motifs):
                motif_length = motif_lengths[i]

                # If the current sequence position is within the bounds of the motif, checks if it matches the motif.
                if sequence_pos + motif_length <= sequence_length:
                    # Gets motif start position from the flat array
                    motif_start = motif_starts[i]

                    # Checks if the motif matches the evaluated sequence.
                    match = True
                    for j in range(motif_length):
                        if cue_sequence[sequence_pos + j] != motifs_flat[motif_start + j]:
                            match = False
                            break
                    # If the motif matches, records the trial type index and moves to the next sequence position.
                    if match:
                        trial_indices[trial_count] = motif_indices[i]
                        trial_count += 1
                        sequence_pos += motif_length
                        motif_found = True
                        break
            # If the function is not able to pair a part of the sequence with a motif, aborts with an error.
            if not motif_found:
                return trial_indices, -1

        return trial_indices[:trial_count], trial_count

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
        # Initializes a second-precise timer to ensure the request is fulfilled within a 2-second timeout
        timeout_timer = PrecisionTimer(precision=TimerPrecisions.SECOND)

        # Ensures that both acquisition marker files are removed before executing mesoscope startup sequence.
        self._mesoscope_data.scanimagepc_data.phosphatase_path.unlink(missing_ok=True)
        self._mesoscope_data.scanimagepc_data.kinase_path.unlink(missing_ok=True)

        # Keeps retrying to activate mesoscope acquisition until success or until the user aborts the acquisition
        outcome = ""
        while outcome != "abort":
            self._microcontrollers.mesoscope_frame.reset_pulse_count()  # Resets the frame counter

            # Ensures that the mesoscope is not currently acquiring frames. If it is acquiring frames, then it has not
            # been set up correctly for acquisition.
            timeout_timer.delay_noblock(1)  # Waits for 1 second to assess whether the mesoscope is acquiring frames.

            # If mesoscope has acquired frames over the delay period, it is not prepared for acquisition.
            if self._microcontrollers.mesoscope_frame.pulse_count > 0:
                message = (
                    "Unable to trigger mesoscope frame acquisition, as the mesoscope is already acquiring frames. "
                    "This indicates that the setupAcquisition() MATLAB function did not run as expected, as that "
                    "function is meant to lock the mesoscope down for acquisition and wait for VRPC to trigger it. "
                    "Re-run the setupAcquisition function before retrying."
                )
                console.echo(message=message, level=LogLevel.ERROR)

            # Otherwise, proceeds with the startup process
            else:
                # Before starting the acquisition, clears any unexpected TIFF / TIF files. This ensures that the data
                # inside the mesoscope directory always perfectly aligns with the number of frame acquisition triggers
                # recorded by the frame monitor module. Note, this is performed only if this is the first call to the
                # start_mesoscope() method during this runtime.
                if not self._mesoscope_started:
                    for pattern in ["*.tif", "*.tiff"]:
                        for file in self._mesoscope_data.scanimagepc_data.mesoscope_data_path.glob(pattern):
                            # Specifically excludes 'zstack.tif' files from this process, as that stack is generated
                            # as part of the acquisition setup procedure.
                            if "zstack" not in file.name:
                                file.unlink(missing_ok=True)

                # Starts the acquisition process by creating the kinase.bin marker. The acquisition function running
                # on the ScanImagePC starts the acquisition process as soon as it detects the presence of the marker
                # file.
                self._mesoscope_data.scanimagepc_data.kinase_path.touch()

                # Ensures that the frame acquisition starts as expected
                message = "Mesoscope acquisition trigger: Sent. Waiting for the mesoscope frame acquisition to start..."
                console.echo(message=message, level=LogLevel.INFO)

                # Waits at most 5 seconds for the mesoscope to acquire at least 10 frames. At ~ 10 Hz, it should take
                # ~ 1 second of downtime.
                timeout_timer.reset()
                while timeout_timer.elapsed < 5:
                    if self._microcontrollers.mesoscope_frame.pulse_count > 10:
                        # Ends the runtime
                        message = "Mesoscope frame acquisition: Started."
                        console.echo(message=message, level=LogLevel.SUCCESS)

                        # Prepares assets used to detect and recover from unwanted acquisition interruptions.
                        self._mesoscope_frame_count = self._microcontrollers.mesoscope_frame.pulse_count
                        self._mesoscope_timer.reset()
                        self._mesoscope_started = True
                        return

                # If the loop above is escaped, this is due to not receiving the mesoscope frame acquisition pulses.
                message = (
                    "The Mesoscope-VR system has requested the mesoscope to start acquiring frames and failed to "
                    "receive 10 frame acquisition triggers over 5 seconds. It is likely that the mesoscope has not "
                    "been armed for externally-triggered frame acquisition or that the mesoscope frame monitoring "
                    "module is not functioning. Make sure the Mesoscope is configured for data acquisition before "
                    "continuing and retry the mesoscope activation."
                )
                console.echo(message=message, level=LogLevel.ERROR)
            outcome = input("Enter 'abort' to abort with an error. Enter anything else to retry: ").lower()

        message = "Runtime aborted due to user request."
        console.error(message=message, error=RuntimeError)
        raise RuntimeError(message)  # Fallback to appease mypy, should not be reachable

    def _stop_mesoscope(self) -> None:
        """Sends the frame acquisition stop TTL pulse to the mesoscope and waits for the frame acquisition to stop.

        This method is used internally to stop the mesoscope frame acquisition as part of the stop() method runtime.

        Notes:
            This method contains an infinite loop that waits for the mesoscope to stop generating frame acquisition
            triggers.
        """
        # Removes the acquisition marker file, which causes the runtime control MATLAB function to stop the acquisition.
        self._mesoscope_data.scanimagepc_data.kinase_path.unlink(missing_ok=True)

        # As a fall-back mechanism for terminating runtimes that failed to initialize, generates the phosphatase.bin
        # marker. The presence of this marker ends the runtime of the MATLAB function if the kinase.bin marker was
        # never created.
        self._mesoscope_data.scanimagepc_data.phosphatase_path.touch()

        # Blocks until the Mesoscope stops sending frame acquisition pulses to the microcontroller.
        message = "Waiting for the Mesoscope to stop acquiring frames..."
        console.echo(message=message, level=LogLevel.INFO)
        self._microcontrollers.mesoscope_frame.reset_pulse_count()  # Resets the frame tracker array
        while True:
            # Delays for 2 seconds. Mesoscope acquires frames at 10 Hz, so if there are no incoming triggers for that
            # period of time, it is safe to assume that the acquisition has stopped.
            self._timestamp_timer.delay_noblock(delay=2000000)
            if self._microcontrollers.mesoscope_frame.pulse_count == 0:
                break  # Breaks the loop
            self._microcontrollers.mesoscope_frame.reset_pulse_count()  # Resets the frame tracker array and waits more

        # Removes the phosphatase marker once the Mesoscope stops sending acquisition triggers.
        self._mesoscope_data.scanimagepc_data.phosphatase_path.unlink(missing_ok=True)

        # NOTE, purposefully avoids flipping the mesoscope_started flag.

    def _checkpoint(self) -> None:
        """Instructs the user to verify the functioning of the water delivery valve and all other components before
        starting the runtime.

        This utility method is called as part of the start() method to allow the user to ensure that all critical system
        elements are ready for runtime. This method is designed to run briefly and is primarily intended for the user
        to test the valve before starting the runtime.
        """
        # Notifies the user about the checkpoint.
        message = (
            "Runtime preparation: Complete. Carry out all final checks and adjustments, such as priming the water "
            "delivery valve. When you are ready to start the runtime, use the UI to 'resume' it."
        )
        console.echo(message=message, level=LogLevel.SUCCESS)

        # Secondary message added in 4.0.0 to address frequent user questions and errors.
        message = (
            "Note: All sensors, including the lick sensor, are DISABLED at this time. If you are running a training "
            "session, apply the electroconductive gel to the headbar to ensure lick sensor works as expected once the "
            "runtime starts."
        )
        console.echo(message=message, level=LogLevel.WARNING)

        # At this point, the user can use the GUI and the Zaber UI to freely manipulate all components of the
        # mesoscope-VR system.
        while self._ui.pause_runtime:
            self._visualizer.update()  # Refreshes the visualizer window.

            if self._ui.reward_signal:
                self._deliver_reward(reward_size=self._ui.reward_volume)

            if self._ui.open_valve:
                self._microcontrollers.valve.set_state(state=True)

            if self._ui.close_valve:
                self._microcontrollers.valve.set_state(state=False)

            # Switches the guidance status in response to user requests
            if self._ui.enable_guidance != self._enable_guidance:
                self._enable_guidance = self._ui.enable_guidance
                self._toggle_lick_guidance(enable_guidance=self._enable_guidance)

            # Switches the reward boundary visibility in response to user requests
            if self._ui.show_reward != self._show_reward_zone_boundary:
                self._show_reward_zone_boundary = self._ui.show_reward
                self._toggle_show_reward(show_reward=self._show_reward_zone_boundary)

            # If the user decides to terminate the runtime at the checkpoint, transitions into the shutdown state
            if self._ui.exit_signal:
                self._terminate_runtime()
                if self._terminated:
                    break

        # Ensures the valve is closed before continuing.
        self._microcontrollers.valve.set_state(state=False)

        # Updates the paused water volume tracker to reflect the total volume of water delivered during the checkpoint.
        self._paused_water_volume += self._microcontrollers.valve.delivered_volume

        # Since deliver_reward() method automatically increments unconsumed reward counter, resets the tracker before
        # starting runtime
        self._unconsumed_reward_count = 0

    def _toggle_lick_guidance(self, *, enable_guidance: bool) -> None:
        """Sets the Virtual Reality task guidance mode to the input state.

        Args:
            enable_guidance: Determines whether to enable or disable the Virtual Reality task guidance.
        """
        # Aborts the runtime early if the acquired session does not use Unity.
        if self._unity is None:
            return

        if not enable_guidance:
            self._unity.send_data(topic=_MesoscopeVRMQTTTopics.DISABLE_GUIDANCE)
        else:
            self._unity.send_data(topic=_MesoscopeVRMQTTTopics.ENABLE_GUIDANCE)

        # Logs the lick guidance state change.
        log_package = LogPackage(
            source_id=self._source_id,
            acquisition_time=np.uint64(self._timestamp_timer.elapsed),
            serialized_data=np.array([_MesoscopeVRLogMessageCodes.GUIDANCE_STATE, enable_guidance], dtype=np.uint8),
        )
        self._logger.input_queue.put(log_package)

    def _toggle_show_reward(self, show_reward: bool) -> None:
        """Sets the visibility of the Virtual Reality task guidance mode's collision boundary.

        Args:
            show_reward: Determines the visibility of the Virtual Reality task guidance mode's collision boundary.
        """
        # Aborts the runtime early if the acquired session does not use Unity.
        if self._unity is None:
            return

        if not show_reward:
            self._unity.send_data(topic=_MesoscopeVRMQTTTopics.HIDE_REWARD_ZONE_BOUNDARY)
        else:
            self._unity.send_data(topic=_MesoscopeVRMQTTTopics.SHOW_REWARD_ZONE_BOUNDARY)

        # Logs the lick guidance collision boundary visibility change.
        log_package = LogPackage(
            source_id=self._source_id,
            acquisition_time=np.uint64(self._timestamp_timer.elapsed),
            serialized_data=np.array([_MesoscopeVRLogMessageCodes.SHOW_REWARD, show_reward], dtype=np.uint8),
        )
        self._logger.input_queue.put(log_package)

    def _change_system_state(self, new_state: int) -> None:
        """Updates and logs the new Mesoscope-VR system state.

        This method is used internally to timestamp and log system state changes, such as transitioning between
        rest and run states during experiment runtimes.

        Args:
            new_state: The byte-code for the newly activated Mesoscope-VR system state.
        """
        # Ensures that the _system_state attribute is set to a non-zero value after runtime initialization. This is
        # used to restore the runtime back to the pre-pause state if the runtime enters the paused state (idle), but the
        # user then chooses to resume the runtime.
        if new_state != _MesoscopeVRStates.IDLE:
            self._system_state = new_state  # Updates the Mesoscope-VR system state

        # Logs the system state update. Uses header-code 1 to indicate that the logged value is the system state-code.
        log_package = LogPackage(
            source_id=self._source_id,
            acquisition_time=np.uint64(self._timestamp_timer.elapsed),
            serialized_data=np.array([_MesoscopeVRLogMessageCodes.SYSTEM_STATE, new_state], dtype=np.uint8),
        )
        self._logger.input_queue.put(log_package)

    def change_runtime_state(self, new_state: int) -> None:
        """Updates and logs the new runtime state (stage).

        Use this method to timestamp and log runtime state (stage) changes, such as transitioning between different
        task goals or experiment phases.

        Args:
            new_state: The integer byte-code for the new runtime state. The code will be serialized as an uint8
                value, so only values between 0 and 255 inclusive are supported.
        """
        # Ensures that the _runtime_state attribute is set to a non-zero value after runtime initialization. This is
        # used to restore the runtime back to the pre-pause state if the runtime enters the paused state (idle), but the
        # user then chooses to resume the runtime.
        if self._runtime_state != 0:
            self._runtime_state = new_state

        # Logs the runtime state update. Uses header-code 2 to indicate that the logged value is the runtime state-code.
        log_package = LogPackage(
            source_id=self._source_id,
            acquisition_time=np.uint64(self._timestamp_timer.elapsed),
            serialized_data=np.array([_MesoscopeVRLogMessageCodes.RUNTIME_STATE, new_state], dtype=np.uint8),
        )
        self._logger.input_queue.put(log_package)

    def idle(self) -> None:
        """Switches the Mesoscope-VR system to the idle state.

        In the idle state, the brake is engaged to prevent the animal from moving the wheel and the screens are turned
        Off. Both torque and encoder monitoring are disabled. Note, idle state is designed to be used exclusively during
        periods where the runtime pauses and does not generate any valid data.

        Notes:
            Unlike the other VR states, setting the system to 'idle' also automatically changes the runtime state to
            0 (idle).

            Idle Mesoscope-VR state is hardcoded as '0'.
        """
        # Switches runtime state to 0
        self.change_runtime_state(new_state=_MesoscopeVRStates.IDLE)

        # Blackens the VR screens
        self._microcontrollers.screens.set_state(state=False)

        # Engages the brake
        self._microcontrollers.brake.set_state(state=True)

        # Disables all sensor monitoring
        self._microcontrollers.wheel_encoder.set_monitoring_state(state=False)
        self._microcontrollers.torque.set_monitoring_state(state=False)
        self._microcontrollers.lick.set_monitoring_state(state=False)

        # Sets system state to 0
        self._change_system_state(_MesoscopeVRStates.IDLE)

    def rest(self) -> None:
        """Switches the Mesoscope-VR system to the rest state.

        In the rest state, the brake is engaged to prevent the animal from moving the wheel. The encoder module is
        disabled, and instead the torque sensor is enabled. The VR screens are switched off, cutting off light emission.

        Notes:
            Rest Mesoscope-VR state is hardcoded as '1'.
        """
        # Enables lick monitoring
        self._microcontrollers.lick.set_monitoring_state(state=True)

        # Blackens the VR screens
        self._microcontrollers.screens.set_state(state=False)

        # Engages the brake
        self._microcontrollers.brake.set_state(state=True)

        # Suspends encoder monitoring.
        self._microcontrollers.wheel_encoder.set_monitoring_state(state=False)

        # Enables torque monitoring.
        self._microcontrollers.torque.set_monitoring_state(state=True)

        # Sets system state to 1
        self._change_system_state(_MesoscopeVRStates.REST)

    def run(self) -> None:
        """Switches the Mesoscope-VR system to the run state.

        In the run state, the brake is disengaged to allow the animal to freely move the wheel. The encoder module is
        enabled to record motion data, and the torque sensor is disabled. The VR screens are switched on to render the
        VR environment.

        Notes:
            Run Mesoscope-VR state is hardcoded as '2'.
        """
        # Enables lick monitoring
        self._microcontrollers.lick.set_monitoring_state(state=True)

        # Initializes encoder monitoring.
        self._microcontrollers.wheel_encoder.set_monitoring_state(state=True)

        # Disables torque monitoring.
        self._microcontrollers.torque.set_monitoring_state(state=False)

        # Activates VR screens.
        self._microcontrollers.screens.set_state(state=True)

        # Disengages the brake
        self._microcontrollers.brake.set_state(state=False)

        # Sets system state to 2
        self._change_system_state(_MesoscopeVRStates.RUN)

    def lick_train(self) -> None:
        """Switches the Mesoscope-VR system to the lick training state.

        In this state, the brake is engaged to prevent the animal from moving the wheel. The encoder module is
        disabled, and the torque sensor is enabled. The VR screens are switched off, cutting off light emission.

        Notes:
            Lick training Mesoscope-VR state is hardcoded as '3'.

            Calling this method automatically switches the runtime state to 255 (active training).
        """
        # Switches runtime state to 255 (active)
        self.change_runtime_state(new_state=255)

        # Blackens the VR screens
        self._microcontrollers.screens.set_state(state=False)

        # Engages the brake
        self._microcontrollers.brake.set_state(state=True)

        # Disables encoder monitoring
        self._microcontrollers.wheel_encoder.set_monitoring_state(state=False)

        # Initiates torque monitoring
        self._microcontrollers.torque.set_monitoring_state(state=True)

        # Initiates lick monitoring
        self._microcontrollers.lick.set_monitoring_state(state=True)

        # Sets system state to 3
        self._change_system_state(_MesoscopeVRStates.LICK_TRAINING)

    def run_train(self) -> None:
        """Switches the Mesoscope-VR system to the run training state.

        In this state, the brake is disengaged, allowing the animal to run on the wheel. The encoder module is
        enabled, and the torque sensor is disabled. The VR screens are switched off, cutting off light emission.

        Notes:
            Run training Mesoscope-VR state is hardcoded as '4'.

            Calling this method automatically switches the runtime state to 255 (active training).
        """
        # Switches runtime state to 255 (active)
        self.change_runtime_state(new_state=255)

        # Blackens the VR screens
        self._microcontrollers.screens.set_state(state=False)

        # Disengages the brake.
        self._microcontrollers.brake.set_state(state=False)

        # Ensures that encoder monitoring is enabled
        self._microcontrollers.wheel_encoder.set_monitoring_state(state=True)

        # Ensures torque monitoring is disabled
        self._microcontrollers.torque.set_monitoring_state(state=False)

        # Initiates lick monitoring
        self._microcontrollers.lick.set_monitoring_state(state=True)

        # Sets system state to 4
        self._change_system_state(_MesoscopeVRStates.RUN_TRAINING)

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
        # Each time visualizer thresholds are updated, also updates the descriptor. For this, converts NumPy scalars to
        # Python float objects (a requirement to make them YAML-compatible).
        if isinstance(self.descriptor, RunTrainingDescriptor):
            self.descriptor.final_run_speed_threshold_cm_s = round(float(speed_threshold), 2)
            # Converts time from milliseconds to seconds
            self.descriptor.final_run_duration_threshold_s = round(float(duration_threshold) / 1000, 2)

        self._visualizer.update_run_training_thresholds(
            speed_threshold=speed_threshold, duration_threshold=duration_threshold
        )

    def _deliver_reward(self, reward_size: float = 5.0) -> None:
        """Uses the solenoid valve to deliver the requested volume of water in microliters.

        Args:
            reward_size: The volume of water to deliver, in microliters. If this argument is set to None, the method
                will use the same volume as used during the previous reward delivery or as set via the GUI.
        """
        self._unconsumed_reward_count += 1  # Increments the unconsumed reward count each time reward is delivered.
        self._microcontrollers.valve.deliver_reward(volume=reward_size)

        # Configures the visualizer to display the valve activation event during the next update cycle.
        self._visualizer.add_valve_event()

    def _simulate_reward(self) -> None:
        """Uses the buzzer controlled by the valve module to deliver an audible tone without delivering any water
        reward.

        This method is used when the animal refuses to consume water rewards during training or experiment runtimes. The
        tone notifies the animal that it performs the task as expected, while simultaneously minimizing water reward
        wasting.
        """
        self._microcontrollers.valve.simulate_reward()

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
        # Only delivers water rewards if the current unconsumed count value is below the user-defined threshold.
        if self._unconsumed_reward_count < self.descriptor.maximum_unconsumed_rewards:
            self._deliver_reward(reward_size=reward_size)
            return True

        # Otherwise, simulates water reward by sounding the buzzer without delivering any water
        self._simulate_reward()
        return False

    def runtime_cycle(self) -> None:
        """Sequentially carries out all cyclic Mesoscope-VR runtime tasks.

        This base cycle method should be called by the runtime logic function as part of its main runtime loop. Calling
        this method synchronizes various assets used by the class instance, such as the GUI, Unity game engine, and the
        visualizer. Also, it is used to monitor critical external assets, such as the Mesoscope and, if necessary,
        pause the runtime and request user intervention.
        """
        # This loop is used to keep the runtime in the runtime cycle if runtime is paused. This effectively suspends
        # external runtime logic.
        while True:
            # Handles animal behavior data updates.
            self._data_cycle()

            # Continuously updates the visualizer
            self._visualizer.update()

            # Synchronizes the runtime state with the state of the user-facing GUI
            self._ui_cycle()

            # If the GUI was used to terminate the runtime, aborts the cycle early
            if self.terminated:
                return

            # If the managed runtime communicates with Unity, synchronizes the state of the Unity virtual task with the
            # state of the runtime (and the GUI).
            if self._unity is not None:
                self._unity_cycle()

            # If the runtime uses the Mesoscope, ensures that the mesoscope is acquiring frames.
            if self._mesoscope_timer is not None:
                self._mesoscope_cycle()

            # As long as the runtime is not paused, returns after running the cycle once. Otherwise, continuously loops
            # the cycle until the user uses the UI to resume the runtime or terminate it.
            if not self._paused:
                return

    def _data_cycle(self) -> None:
        """Queries and synchronizes changes to animal runtime behavior metrics with Unity and the visualizer class.

        This method reads the data sent by low-level data acquisition modules and updates class attributes used to
        support runtime logic, data visualization, and Unity VR task. If necessary, it directly communicates the updates
        to Unity via MQTT and to the visualizer through appropriate methods.
        """
        # Reads the total distance traveled by the animal and the current position of the animal in Unity units. These
        # values are accessed together to ensure the animal does not accumulate more distance or position data between
        # accessing these two values.
        traveled_distance = self._microcontrollers.wheel_encoder.traveled_distance
        current_position = self._microcontrollers.wheel_encoder.absolute_position

        # The speed value is updated over ~50 millisecond windows. This gives a good balance between smoothness
        # and sensitivity (on top of 'metal' smoothing built into the encoder module).
        if self._speed_timer.elapsed >= self._speed_calculation_window:
            self._speed_timer.reset()  # Resets the timer

            # Determines the total distance covered by the animal over the window of 50 ms, converts from cm / ms to
            # cm / s, and casts to the type expected by the visualizer class.
            running_speed = np.float64(((traveled_distance - self._distance) / 100) * 1000)

            # Caches the new traveled distance and the running speed value to class attributes.
            self._distance = traveled_distance
            self._running_speed = running_speed  # Also stores the value for sharing with training runtime.

            # Updates the running speed value in the visualizer.
            self._visualizer.update_running_speed(running_speed)

        # Both position and traveled distance are also used to support Unity-based virtual reality task execution. If
        # Unity is not running, then only the total traveled distance is used during runtime to track the animal's
        # running speed.
        if self._unity is not None:
            # First, computes the change in the animal's position relative to the previous cycle and if it is
            # significant, sends the position update to Unity.

            # Subtracting previous position from current position correctly maps positive deltas to moving forward and
            # negative deltas to moving backward
            position_delta = current_position - self._position

            # If position changed, updates the cached position value to use during later parsing cycles and sends
            # position delta to unity.
            if position_delta != 0:
                # Overwrites the cached position with the new data
                self._position = current_position

                # Encodes the motion data into the format expected by the GIMBL Unity module and serializes it into a
                # byte-string.
                json_string = dumps(obj={"movement": position_delta})
                byte_array = json_string.encode("utf-8")

                # Publishes the motion to the appropriate MQTT topic.
                self._unity.send_data(topic=self._microcontrollers.wheel_encoder.mqtt_topic, payload=byte_array)

            # Checks if the animal has traveled beyond the end of the current trial. Specifically, checks whether the
            # total traveled distance exceeds the cumulative traveled distance expected at the end of the current
            # trial.
            if traveled_distance > self._trial_distances[self._completed_trials]:
                # Updates the completed trials counter. This automatically adjusts reward size and cumulative
                # distance tracking for the next trial.
                self._completed_trials += 1

                # If the completed trial was not rewarded, increments the unrewarded trial counter.
                if not self._trial_rewarded:
                    self._failed_trials += 1
                else:
                    # Otherwise, resets the failed trial sequence to 0.
                    self._failed_trials = 0

                # Resets the trial reward tracker for the next trial
                self._trial_rewarded = False

                # If this trial was not rewarded and failing this trial caused the overall sequence of failed trials
                # to exceed the threshold, re-enabled guidance for the pre-specified number of recovery trials.
                if self._failed_trials >= self._failed_trial_threshold and self._recovery_trials > 0:
                    self._failed_trials = 0  # Resets the failed trial counter
                    self._guided_trials = self._recovery_trials
                    self._ui.set_guidance_state(enabled=True)

        # If the lick tracker indicates that the sensor has detected new licks, handles incoming lick data
        lick_count = self._microcontrollers.lick.lick_count
        if lick_count > self._lick_count:
            # Updates the local lick counter with the new data
            self._lick_count = lick_count

            # Whenever the animal licks the water delivery tube, it is consuming any available rewards. Resets the
            # unconsumed count whenever new licks are detected.
            self._unconsumed_reward_count = 0

            # Configures the visualizer to render a new lick event during the next update cycle.
            self._visualizer.add_lick_event()

            # If this runtime uses Unity, also notifies Unity about the detected lick event.
            if self._unity is not None:
                self._unity.send_data(topic=self._microcontrollers.lick.mqtt_topic, payload=None)

        # If the water delivery valve tracker indicates that the valve delivered a water reward, determine the delivered
        # volume and, depending on whether the runtime is active or paused, updates the appropriate tracker attribute.
        dispensed_water = self._microcontrollers.valve.delivered_volume - (
            self._paused_water_volume + self._delivered_water_volume
        )
        if dispensed_water > 0:
            if self._paused:
                self._paused_water_volume += dispensed_water
            else:
                self._delivered_water_volume += dispensed_water

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
        # Aborts early if this runtime does not use Unity.
        if self._unity is None:
            return

        # If Unity sends updates to the Mesoscope-VR system, receives and processes the data. Note, this discards
        # all unexpected data
        if self._unity.has_data:
            topic: str
            topic, _ = self._unity.get_data()

            # Uses the reward volume specified during startup (5.0).
            if topic == self._microcontrollers.valve.mqtt_topic:
                # This method either delivers the reward or simulates it with the tone, depending on the unconsumed
                # reward tracker. The size of the reward matches the reward size for the current trial
                # (for most trials it would be 5.0 uL).
                self.resolve_reward(reward_size=self._trial_rewards[self._completed_trials])

                # Decrements the guided trial counter each time Unity instructs the runtime to deliver a reward.
                # Receiving reward delivery commands indicates that the animal performs the task as expected. This is
                # only done when guided trials are enabled.
                if self._guided_trials > 0:
                    self._guided_trials -= 1

                    # If the cycle decremented the guided trials tracker to 0, disables lick guidance mode if it is
                    # enabled.
                    if self._guided_trials == 0:
                        self._ui.set_guidance_state(enabled=False)

                # Also flips the trial reward flag to True if the animal receives the reward during this trial.
                self._trial_rewarded = True

            # If Unity runtime (game mode) terminates, Unity sends a message to the termination topic. In turn, the
            # runtime uses this as an indicator to reset the task logic.
            if topic == _MesoscopeVRMQTTTopics.UNITY_TERMINATION:
                # Switches the runtime into the paused state and sets the unity termination tracker
                self._unity_terminated = True
                self._pause_runtime()
                message = "Emergency pause: Engaged. Reason: Unity sent a runtime termination message."
                console.echo(message=message, level=LogLevel.ERROR)

                # Reads the total distance traveled by the animal at this point. Since this is done after cutting off
                # the wheel motion stream (by transitioning into paused (idle) state), there should be minimal
                # deviation of the read position and the physical position of the animal.
                traveled_distance = float(self._microcontrollers.wheel_encoder.traveled_distance)
                # Converts float to a byte array using little-endian format
                distance_bytes = np.array([traveled_distance], dtype="<i8").view(np.uint8)

                # Generates a new log entry with the message ID code 5. This code is statically used to indicate that
                # the Unity runtime has been terminated. The message includes the current position of the animal in
                # Unity units, stored as a byte array (8 bytes). The position stamp is then used during behavior data
                # processing to artificially 'fuse' multiple cue sequences together if the user chooses to restart the
                # unity task and resume the runtime.
                log_package = LogPackage(
                    source_id=self._source_id,
                    acquisition_time=np.uint64(self._timestamp_timer.elapsed),
                    serialized_data=np.concatenate(
                        [np.array([_MesoscopeVRLogMessageCodes.DISTANCE_SNAPSHOT], dtype=np.uint8), distance_bytes]
                    ),
                )
                self._logger.input_queue.put(log_package)
                message = (
                    "Address the issue that prevents Unity game engine from running and resume the runtime. Re-arm the "
                    "Unity scene (hit play) before resuming the runtime. Alternatively, terminate the runtime to "
                    "attempt graceful shutdown."
                )
                console.echo(message=message, level=LogLevel.INFO)
                return

    def _ui_cycle(self) -> None:
        """Queries the state of various GUI components and adjusts the runtime behavior accordingly.

        This utility method cycles through various user-addressable runtime components and, depending on corresponding
        UI states, executes the necessary functionality or updates associated parameters. In essence, calling this
        method synchronizes the runtime with the state of the runtime control GUI.

        Notes:
            This method is designed to be called repeatedly as part of the main runtime cycle loop (via the user-facing
            runtime_cycle() method).
        """
        # If the ui detects a pause command, enters a pause loop. This effectively locks the runtime into the 'pause'
        # state, ceasing all runtime logic execution until the user resumes the runtime or terminates it.
        if self._ui.pause_runtime and not self._paused:
            self._pause_runtime()

        elif not self._ui.pause_runtime and self._paused:
            # If the user sends a resume command, resumes the runtime and adjusts certain class attributes to help
            # runtime logic functions discount (ignore) the time spent in the paused state.
            self._resume_runtime()

        # If the user sent the abort command, terminates the runtime early with an error message.
        if self._ui.exit_signal:
            self._terminate_runtime()

            # If the user confirms runtime termination, breaks the ui cycle to expedite the runtime shutdown sequence.
            if self.terminated:
                return

        # If the user toggles manual reward delivery via the GUI, delivers a water reward to the animal.
        if self._ui.reward_signal:
            # This specifically uses the '_deliver_reward' method to ensure the reward is delivered regardless of
            # the unconsumed reward tracker state. Also, always uses the reward volume specified by the GUI.
            self._deliver_reward(reward_size=self._ui.reward_volume)

            # Ensures that manual rewards delivered during the pause state are not counted against the unconsumed reward
            # threshold.
            if self._paused:
                self._unconsumed_reward_count = 0

        # If the user changes the guidance state via the UI, instructs Unity to update the state to match GUI setting.
        if self._ui.enable_guidance != self._enable_guidance:
            self._enable_guidance = self._ui.enable_guidance
            self._toggle_lick_guidance(enable_guidance=self._enable_guidance)

        # If the user changes the reward collision wall visibility state via the UI, instructs Unity to update the
        # state to match the GUI setting.
        if self._ui.show_reward != self._show_reward_zone_boundary:
            self._show_reward_zone_boundary = self._ui.show_reward
            self._toggle_show_reward(show_reward=self._show_reward_zone_boundary)

    def _mesoscope_cycle(self) -> None:
        """Checks whether mesoscope frame acquisition is active and, if not, emergency pauses the runtime.

        This method is designed to be called repeatedly as part of the system runtime cycle. It monitors mesoscope
        frame acquisition triggers, and if it detects an acquisition pause longer than ~300 milliseconds, it activates
        the emergency pause state, similar to how Unity termination messages are handled by the _unity_cycle() method.
        """
        # Aborts early if mesoscope_timer is not initialized, it has been less than ~300 milliseconds since the last
        # mesoscope frame acquisition check, or the mesoscope runtime appears to be terminated.
        if (
            self._mesoscope_timer is None
            or self._mesoscope_timer.elapsed < self._mesoscope_frame_delay
            or self._mesoscope_terminated
        ):
            return

        # If mesoscope has acquired more frames since the last check, updates the cached frame count and returns
        # to caller.
        if self._mesoscope_frame_count < self._microcontrollers.mesoscope_frame.pulse_count:
            self._mesoscope_frame_count = self._microcontrollers.mesoscope_frame.pulse_count
            self._mesoscope_timer.reset()  # Resets the timer to start timing the next cycle
            return

        # Otherwise, if the mesoscope has not been acquiring frames for the past 300 milliseconds, enters emergency
        # pause state.
        self._mesoscope_terminated = True  # Sets the termination flag
        self._pause_runtime()  # Pauses the runtime.
        message = "Emergency pause: Engaged. Reason: Mesoscope stopped sending frame acquisition triggers. "
        console.echo(message=message, level=LogLevel.ERROR)
        self._stop_mesoscope()  # Ensures that the mesoscope runtime markers are removed to facilitate restarting.
        message = (
            "Address the issue that prevents the Mesoscope from acquiring frames and resume the runtime. Follow "
            "additional instructions displayed after resuming the runtime to re-arm the mesoscope to continue "
            "acquiring frames for the current runtime. Alternatively, terminate the runtime to attempt graceful "
            "shutdown."
        )
        console.echo(message=message, level=LogLevel.INFO)
        return

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
        # Ensures that the GUI reflects that the runtime is paused. While most paused states originate from the GUI,
        # certain events may cause the main runtime cycle to activate the paused state bypassing the GUI.
        if not self._ui.pause_runtime:
            self._ui.set_pause_state(paused=True)

        # Records pause onset time
        self._pause_start_time = self._timestamp_timer.elapsed

        # Switches the Mesoscope-VR system into the idle state.
        self.idle()

        # Notifies the user that the runtime has been paused
        message = "Mesoscope-VR runtime: Paused."
        console.echo(message=message, level=LogLevel.WARNING)

        # Sets the paused flag
        self._paused = True

    def _resume_runtime(self) -> None:
        """Resumes the managed runtime.

        This method restores the system back to the original running state after it has been paused with the
        _pause_runtime() method. As part of this process, it also updates the 'paused_time' to reflect the time, in
        seconds, spent in the paused state.
        """
        message = "Mesoscope-VR runtime: Resumed."
        console.echo(message=message, level=LogLevel.SUCCESS)

        # If Unity or mesoscope terminated during runtime, attempts to re-initialize Unity and restart the Mesoscope.
        if self._unity_terminated:
            # When the Unity game cycles, it resets the sequence of VR wall cues. This re-queries the new wall cue
            # sequence to enable accurate tracking of the animal's position in VR after reset.
            self._get_cue_sequence()

            # Resets the termination tracker if cue_sequence retrieval succeeds, indicating that the Unity has
            # been restarted.
            self._unity_terminated = False

        if self._mesoscope_terminated:
            # Restarting the Mesoscope is slightly different from starting it, as the user needs to call a special
            # version of the setupAcquisition() function. Instructs the user to call the function and then enters the
            # Mesoscope start sequence.
            message = (
                "If necessary call the setupAcquisition(hSI, hSICtl, recovery=true) command in the MATLAB command "
                "line interface before proceeding. When this function is called in the 'recovery' mode, it correctly "
                "re-sets the system to resume an interrupted acquisition."
            )
            console.echo(message=message, level=LogLevel.WARNING)
            input("Enter anything to continue: ")

            self._start_mesoscope()

            # Resets the termination tacker if Mesoscope acquisition restarts successfully.
            self._mesoscope_terminated = False

        # Updates the 'paused_time' value to reflect the time spent inside the 'paused' state. Most runtimes use this
        # public attribute to adjust the execution time of certain runtime stages or the runtime altogether.
        pause_time = round(
            convert_time(time=self._timestamp_timer.elapsed - self._pause_start_time, from_units="us", to_units="s")
        )
        self.paused_time += pause_time

        # Restores the runtime state back to the value active before the pause.
        self.change_runtime_state(new_state=self._runtime_state)

        # Restores the system state to pre-pause condition.
        if self._system_state == _MesoscopeVRStates.IDLE:
            # This is a rare case where the pause was triggered before a valid non-idle state was activated by the
            # runtime logic function. While rare, it is not technically impossible, so it is supported here
            self.idle()
        elif self._system_state == _MesoscopeVRStates.REST:
            self.rest()
        elif self._system_state == _MesoscopeVRStates.RUN:
            self.run()
        elif self._system_state == _MesoscopeVRStates.LICK_TRAINING:
            self.lick_train()
        elif self._system_state == _MesoscopeVRStates.RUN_TRAINING:
            self.run_train()

        # Resets the paused flag
        self._paused = False

    def _terminate_runtime(self) -> None:
        """Verifies that the user intends to abort the runtime via terminal prompt and, if so, sets the runtime into
        the termination mode.

        When the runtime is switched into the termination mode, it will sequentially escape all internal and external
        cycle loops and attempt to perform a graceful shutdown procedure.
        """
        # Verifies that the user intends to abort the runtime to avoid 'misclick' terminations.
        message = "Runtime abort signal: Received. Are you sure you want to abort the runtime?"
        console.echo(message=message, level=LogLevel.WARNING)
        while True:
            answer = input("Enter 'yes' or 'no': ")

            # Sets the runtime into the termination state, which aborts all instance cycles and the outer logic function
            # cycle.
            if answer.lower() == "yes":
                self._terminated = True
                return

            # Returns without terminating the runtime
            if answer.lower() == "no":
                return

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
        self._guided_trials = initial_guided_trials  # Resets the guided trial count.
        self._failed_trials = 0  # Resets the failed trial sequence tracker

        # Updates failed trial threshold and recovery trial count
        self._failed_trial_threshold = failed_trials_threshold
        self._recovery_trials = recovery_guided_trials

        # Enables lick guidance via direct GUI manipulation to run the requested number of initial trials in the
        # guided mode. If the initial guided trial number is 0, does not activate lick guidance.
        if self._guided_trials > 0:
            self._ui.set_guidance_state(enabled=True)

    @property
    def terminated(self) -> bool:
        """Returns True if the runtime is in the termination mode.

        This property is used by external logic functions to detect and execute runtime termination commands issued via
        GUI.
        """
        return self._terminated

    @property
    def running_speed(self) -> np.float64:
        """Returns the current running speed of the animal in centimeters per second."""
        return self._running_speed

    @property
    def speed_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the running speed threshold during run training."""
        return self._ui.speed_modifier

    @property
    def duration_modifier(self) -> int:
        """Returns the current user-defined modifier to apply to the duration threshold during run training."""
        return self._ui.duration_modifier

    @property
    def dispensed_water_volume(self) -> float:
        """Returns the total volume of water, in microliters, dispensed by the valve during the current runtime."""
        return float(self._delivered_water_volume)


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
    message = "Initializing lick training runtime..."
    console.echo(message=message, level=LogLevel.INFO)

    # Queries the data acquisition system runtime parameters
    system_configuration = get_system_configuration()

    # Verifies that the target project exists
    project_directory = system_configuration.paths.root_directory.joinpath(project_name)
    if not project_directory.exists():
        message = (
            f"Unable to execute the lick training for the animal {animal_id} of project {project_name}. The target "
            f"project does not exist on the local machine. Use the 'sl-create-project' command to create the project "
            f"before running training or experiment sessions."
        )
        console.error(message=message, error=FileNotFoundError)

    # These checks have been added in version 4.0.0 to help users abide by the 'one animal one project' policy. Now all
    # runtimes require each animal to be assigned to a single project.
    animal_projects = get_animal_project(animal_id=animal_id)
    if len(animal_projects) > 1:  # Rare case, often indicative of old migration pipeline use
        message = (
            f"Unable to execute the lick training for the animal {animal_id} of project {project_name}. The animal "
            f"is associated with multiple projects on the local machine, which is not allowed. Remove the animal from "
            f"all extra projects and rerun the training."
        )
        console.error(message=message, error=ValueError)
    elif len(animal_projects) == 1 and animal_projects[0] != project_name:  # This indicates user error
        message = (
            f"Unable to execute the lick training for the animal {animal_id} and project {project_name}. The animal "
            f"is already associated with a different project '{animal_projects[0]}'. Either adjust the project name to "
            f"match the animal's current project or use the 'sl-migrate-animal' CLI command to first migrate the "
            f"animal to the desired project and rerun the training."
        )
        console.error(message=message, error=ValueError)

    # Queries the current Python and library version information. This is then used to initialize the SessionData
    # instance.
    python_version, library_version = get_version_data()

    # Initializes data-management classes for the runtime. Note, SessionData creates the necessary session directory
    # hierarchy as part of this initialization process
    session_data = SessionData.create(
        project_name=project_name,
        animal_id=animal_id,
        session_type=SessionTypes.LICK_TRAINING,
        python_version=python_version,
        sl_experiment_version=library_version,
    )
    mesoscope_data = MesoscopeData(session_data=session_data)

    # If the managed animal has cached data from a previous lick training session and the function is
    # configured to load previous data, replaces all runtime-defining parameters passed to the function with data
    # loaded from the previous session's descriptor file
    previous_descriptor_path = mesoscope_data.vrpc_data.session_descriptor_path
    if previous_descriptor_path.exists() and load_previous_parameters:
        previous_descriptor: LickTrainingDescriptor = LickTrainingDescriptor.from_yaml(
            file_path=previous_descriptor_path
        )
        maximum_reward_delay = previous_descriptor.maximum_reward_delay_s
        minimum_reward_delay = previous_descriptor.minimum_reward_delay_s

    # Initializes the timer used to enforce reward delays
    delay_timer = PrecisionTimer(precision=TimerPrecisions.SECOND)

    message = "Generating the pseudorandom reward delay sequence..."
    console.echo(message=message, level=LogLevel.INFO)

    # Converts maximum volume to uL and divides it by 5 uL (reward size) to get the number of delays to sample from
    # the delay distribution
    num_samples = np.floor((maximum_water_volume * 1000) / 5).astype(np.uint64)

    # Generates samples from a uniform distribution within delay bounds
    samples = np.random.uniform(minimum_reward_delay, maximum_reward_delay, num_samples)

    # Calculates cumulative training time for each sampled delay. This communicates the total time passed when each
    # reward is delivered to the animal
    cumulative_time = np.cumsum(samples)

    # Finds the maximum number of samples that fits within the maximum training time. This assumes that to consume 1
    # ml of water, the animal would likely need more time than the maximum allowed training time, so we need to slice
    # the sampled delay array to fit within the time boundary.
    max_samples_idx = np.searchsorted(cumulative_time, maximum_training_time * 60, side="right")

    # Slices the samples array to make the total training time be roughly the maximum requested duration.
    reward_delays: NDArray[np.float64] = samples[:max_samples_idx]

    message = (
        f"Generated a sequence of {len(reward_delays)} rewards with the total cumulative runtime of "
        f"{np.round(cumulative_time[max_samples_idx - 1] / 60, decimals=3)} minutes."
    )
    console.echo(message=message, level=LogLevel.SUCCESS)

    # If session runtime is limited by the total volume of delivered water, rather than the maximum runtime, clips the
    # total training time at the point where the maximum allowed water volume is delivered.
    if len(reward_delays) == len(cumulative_time):
        # Actual session time is the accumulated delay converted from seconds to minutes at the last index.
        maximum_training_time = int(np.ceil(cumulative_time[-1] / 60))

    # If the maximum unconsumed reward count is below 1, disables the feature by setting the number to match the
    # number of rewards to be delivered.
    if maximum_unconsumed_rewards < 1:
        maximum_unconsumed_rewards = len(reward_delays)

    # Pre-generates the SessionDescriptor class and populates it with training data.
    descriptor = LickTrainingDescriptor(
        maximum_reward_delay_s=maximum_reward_delay,
        minimum_reward_delay_s=minimum_reward_delay,
        maximum_training_time_m=maximum_training_time,
        maximum_water_volume_ml=maximum_water_volume,
        experimenter=experimenter,
        mouse_weight_g=animal_weight,
        dispensed_water_volume_ml=0.00,
        maximum_unconsumed_rewards=maximum_unconsumed_rewards,
        incomplete=True,  # Has to be initialized to True, so that if the session aborts, it is marked as incomplete
    )

    runtime: _MesoscopeVRSystem | None = None
    try:
        # Initializes the runtime class
        runtime = _MesoscopeVRSystem(session_data=session_data, session_descriptor=descriptor)

        # Verifies that the Water Restriction log and the Surgery log Google Sheets are accessible. To do so,
        # instantiates both classes to run through the init checks. The classes are later re-instantiated during
        # session data preprocessing
        _ = WaterLog(
            animal_id=int(animal_id),
            session_date=session_data.session_name,
            credentials_path=system_configuration.paths.google_credentials_path,
            sheet_id=system_configuration.sheets.water_log_sheet_id,
        )
        _ = SurgeryLog(
            project_name=project_name,
            animal_id=int(animal_id),
            credentials_path=system_configuration.paths.google_credentials_path,
            sheet_id=system_configuration.sheets.surgery_sheet_id,
        )

        # Initializes all runtime assets and guides the user through hardware-specific runtime preparation steps.
        runtime.start()

        # If the user chose to terminate the runtime during initialization checkpoint, raises an error to jump to the
        # shutdown runtime sequence, bypassing all other runtime preparation steps.
        if runtime.terminated:
            # Note, this specific type of errors should not be raised by any other runtime component. Therefore, it is
            # possible to handle this type of exceptions as a unique marker for early user-requested runtime
            # termination.
            message = "The runtime was terminated early due to user request."
            console.echo(message=message, level=LogLevel.SUCCESS)
            raise RecursionError

        # Marks the session as fully initialized. This prevents session data from being automatically removed by
        # 'purge' runtimes.
        session_data.runtime_initialized()

        # Switches the system into lick-training mode
        runtime.lick_train()

        message = "Lick training: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

        # Loops over all delays and delivers reward via the lick tube as soon as the delay expires.
        delay_timer.reset()
        for delay in tqdm(
            reward_delays,
            desc="Delivered water rewards",
            unit="reward",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} rewards [{elapsed}]",
        ):
            # This loop is executed while the code is waiting for the delay to pass. Anything that needs to be done
            # during the delay has to go here. IF the runtime is paused during the delay cycle, the time spent in the
            # paused is used to discount the delay. This is in contrast to other runtimes, where pause time actually
            # INCREASES the overall runtime.
            while delay_timer.elapsed < (delay - runtime.paused_time):
                runtime.runtime_cycle()  # Repeatedly calls the runtime cycle during the delay period

            # If the user sent the abort command, terminates the training early.
            if runtime.terminated:
                message = (
                    "Lick training abort signal detected. Aborting the lick training with a graceful shutdown "
                    "procedure..."
                )
                console.echo(message=message, level=LogLevel.ERROR)
                break  # Breaks the for loop

            # Resets the delay timer immediately after exiting the delay loop
            delay_timer.reset()

            # Clears the paused time at the end of each delay cycle. This has to be done to prevent future delay
            # loops from ending earlier than expected unless the runtime is paused again as part of that loop.
            runtime.paused_time = 0

            # Delivers 5 uL of water to the animal or simulates the reward if the animal is not licking
            runtime.resolve_reward(reward_size=5.0)

        # Ensures the animal has time to consume the last reward before the LickPort is moved out of its range. Uses
        # the maximum possible time interval as the delay interval.
        delay_timer.delay_noblock(maximum_reward_delay)

    # RecursionErrors should not be raised by any runtime component except in the case that the user wants to terminate
    # the runtime as part of the startup checkpoint. Therefore, silences the error.
    except RecursionError:
        pass

    # Ensures that the function always attempts the graceful shutdown procedure, even if it encounters runtime errors.
    finally:
        # If the runtime was initialized, attempts to gracefully terminate runtime assets
        if runtime is not None:
            runtime.stop()

        # If the session runtime terminates before the session was initialized, removes session data from all
        # sources before shutting down.
        if session_data.raw_data.nk_path.exists():
            message = (
                "The runtime was unexpectedly terminated before it was able to initialize and start all assets. "
                "Removing all leftover data from the uninitialized session from all destinations..."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            purge_session(session_data)

        message = "Lick training runtime: Complete."
        console.echo(message=message, level=LogLevel.SUCCESS)


def run_training_logic(
    experimenter: str,
    project_name: str,
    animal_id: str,
    animal_weight: float,
    initial_speed_threshold: float = 0.50,
    initial_duration_threshold: float = 0.50,
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
    message = "Initializing run training runtime..."
    console.echo(message=message, level=LogLevel.INFO)

    # Queries the data acquisition system runtime parameters
    system_configuration = get_system_configuration()

    # Verifies that the target project exists
    project_directory = system_configuration.paths.root_directory.joinpath(project_name)
    if not project_directory.exists():
        message = (
            f"Unable to execute the run training for the animal {animal_id} of project {project_name}. The target "
            f"project does not exist on the local machine. Use the 'sl-create-project' command to create the project "
            f"before running training or experiment sessions."
        )
        console.error(message=message, error=FileNotFoundError)

    # These checks have been added in version 4.0.0 to help users abide by the 'one animal one project' policy. Now all
    # runtimes require each animal to be assigned to a single project.
    animal_projects = get_animal_project(animal_id=animal_id)
    if len(animal_projects) > 1:  # Rare case, often indicative of old migration pipeline use
        message = (
            f"Unable to execute the run training for the animal {animal_id} of project {project_name}. The animal "
            f"is associated with multiple projects on the local machine, which is not allowed. Remove the animal from "
            f"all extra projects and rerun the training."
        )
        console.error(message=message, error=ValueError)
    elif len(animal_projects) == 1 and animal_projects[0] != project_name:  # This indicates user error
        message = (
            f"Unable to execute the run training for the animal {animal_id} and project {project_name}. The animal "
            f"is already associated with a different project '{animal_projects[0]}'. Either adjust the project name to "
            f"match the animal's current project or use the 'sl-migrate-animal' CLI command to first migrate the "
            f"animal to the desired project and rerun the training."
        )
        console.error(message=message, error=ValueError)

    # Queries the current Python and library version information. This is then used to initialize the SessionData
    # instance.
    python_version, library_version = get_version_data()

    # Initializes data-management classes for the runtime. Note, SessionData creates the necessary session directory
    # hierarchy as part of this initialization process
    session_data = SessionData.create(
        project_name=project_name,
        animal_id=animal_id,
        session_type=SessionTypes.RUN_TRAINING,
        python_version=python_version,
        sl_experiment_version=library_version,
    )
    mesoscope_data = MesoscopeData(session_data=session_data)

    # If the managed animal has cached data from a previous run training session and the function is
    # configured to load previous data, replaces all runtime-defining parameters passed to the function with data
    # loaded from the previous session's descriptor file
    previous_descriptor_path = mesoscope_data.vrpc_data.session_descriptor_path
    if previous_descriptor_path.exists() and load_previous_parameters:
        previous_descriptor: RunTrainingDescriptor = RunTrainingDescriptor.from_yaml(file_path=previous_descriptor_path)

        # Sets initial speed and duration thresholds to the FINAL thresholds from the previous session. This way, each
        # consecutive run training session begins where the previous one has ended.
        initial_speed_threshold = previous_descriptor.final_run_speed_threshold_cm_s
        initial_duration_threshold = previous_descriptor.final_run_duration_threshold_s

    # Initializes the timers used during runtime
    runtime_timer = PrecisionTimer(precision=TimerPrecisions.SECOND)
    running_duration_timer = PrecisionTimer(precision=TimerPrecisions.MILLISECOND)
    epoch_timer = PrecisionTimer(precision=TimerPrecisions.MILLISECOND)

    # Initializes assets used to guard against interrupting run epochs for mice that take many large steps. For mice
    # with a distinct walking pattern of many very large steps, the speed transiently dips below the threshold for a
    # very brief moment of time, flagging the epoch as unrewarded. To avoid this issue, instead of interrupting the
    # epoch outright, we now allow the speed to be below the threshold for a short period of time. These assets
    # help with that task pattern.
    epoch_timer_engaged: bool = False
    maximum_idle_time = max(0.0, maximum_idle_time) * 1000  # Ensures positive values or zero and converts to msec

    # Initializes assets used to ensure that the animal consumes delivered water rewards.
    if maximum_unconsumed_rewards < 1:
        # If the maximum unconsumed reward count is below 1, disables the feature by setting the number to match the
        # maximum number of rewards that can be delivered during runtime.
        maximum_unconsumed_rewards = int(np.ceil(maximum_water_volume / 0.005))

    # Converts all arguments used to determine the speed and duration threshold over time into numpy variables to
    # optimize main loop runtime speed:
    initial_speed = np.float64(initial_speed_threshold)  # In centimeters per second
    maximum_speed = np.float64(5)  # In centimeters per second
    speed_step = np.float64(speed_increase_step)  # In centimeters per second

    initial_duration = np.float64(initial_duration_threshold * 1000)  # In milliseconds
    maximum_duration = np.float64(5000)  # In milliseconds
    duration_step = np.float64(duration_increase_step * 1000)  # In milliseconds

    # The way 'increase_threshold' is used requires it to be greater than 0. So if a threshold of 0 is passed, the
    # system sets it to a very small number instead, which functions similar to it being 0, but does not produce an
    # error. Specifically, this prevents the 'division by zero' error.
    if increase_threshold < 0:
        increase_threshold = 0.000000000001

    water_threshold = np.float64(increase_threshold * 1000)  # In microliters
    maximum_volume = np.float64(maximum_water_volume * 1000)  # In microliters

    # Converts the training time from minutes to seconds to make it compatible with the timer precision.
    training_time = maximum_training_time * 60

    # Initializes internal tracker variables:
    # Tracks the data necessary to update the training progress bar
    previous_time = 0

    # Tracks when speed and / or duration thresholds are updated. This is necessary to redraw the threshold lines in
    # the visualizer plot
    previous_speed_threshold = copy.copy(initial_speed)
    previous_duration_threshold = copy.copy(initial_duration)

    # This one-time tracker is used to initialize the speed and duration threshold visualization.
    once = True

    # Pre-generates the SessionDescriptor class and populates it with training data
    descriptor = RunTrainingDescriptor(
        dispensed_water_volume_ml=0.0,
        final_run_speed_threshold_cm_s=initial_speed_threshold,
        final_run_duration_threshold_s=initial_duration_threshold,
        initial_run_speed_threshold_cm_s=initial_speed_threshold,
        initial_run_duration_threshold_s=initial_duration_threshold,
        increase_threshold_ml=increase_threshold,
        run_speed_increase_step_cm_s=speed_increase_step,
        run_duration_increase_step_s=duration_increase_step,
        maximum_training_time_m=maximum_training_time,
        maximum_water_volume_ml=maximum_water_volume,
        maximum_unconsumed_rewards=maximum_unconsumed_rewards,
        maximum_idle_time_s=round(maximum_idle_time / 1000, 3),  # Converts back to seconds for storage purposes.
        experimenter=experimenter,
        mouse_weight_g=animal_weight,
        incomplete=True,  # Has to be initialized to True, so that if the session aborts, it is marked as incomplete
    )

    runtime: _MesoscopeVRSystem | None = None
    try:
        # Initializes the runtime class
        runtime = _MesoscopeVRSystem(session_data=session_data, session_descriptor=descriptor)

        # Verifies that the Water Restriction log and the Surgery log Google Sheets are accessible. To do so,
        # instantiates both classes to run through the init checks. The classes are later re-instantiated during
        # session data preprocessing
        _ = WaterLog(
            animal_id=int(animal_id),
            session_date=session_data.session_name,
            credentials_path=system_configuration.paths.google_credentials_path,
            sheet_id=system_configuration.sheets.water_log_sheet_id,
        )
        _ = SurgeryLog(
            project_name=project_name,
            animal_id=int(animal_id),
            credentials_path=system_configuration.paths.google_credentials_path,
            sheet_id=system_configuration.sheets.surgery_sheet_id,
        )

        # Initializes all runtime assets and guides the user through hardware-specific runtime preparation steps.
        runtime.start()

        # If the user chose to terminate the runtime during initialization checkpoint, raises an error to jump to the
        # shutdown runtime sequence, bypassing all other runtime preparation steps.
        if runtime.terminated:
            # Note, this specific type of errors should not be raised by any other runtime component. Therefore, it is
            # possible to handle this type of exceptions as a unique marker for early user-requested runtime
            # termination.
            message = "The runtime was terminated early due to user request."
            console.echo(message=message, level=LogLevel.SUCCESS)
            raise RecursionError

        # Marks the session as fully initialized. This prevents session data from being automatically removed by
        # 'purge' runtimes.
        session_data.runtime_initialized()

        # Switches the runtime into the run-training mode
        runtime.run_train()

        message = "Run training: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

        # Creates a tqdm progress bar that tracks the overall training progress by communicating the total volume of
        # water delivered to the animal
        progress_bar = tqdm(
            total=round(maximum_water_volume, ndigits=3),
            desc="Delivered water volume",
            unit="ml",
            bar_format="{l_bar}{bar}| {n:.3f}/{total:.3f} {postfix}",
        )

        runtime_timer.reset()
        running_duration_timer.reset()  # It is critical to reset both timers at the same time.

        # This is the main runtime loop of the run training mode.
        while runtime_timer.elapsed < (training_time + runtime.paused_time):
            runtime.runtime_cycle()  # Repeatedly calls the runtime cycle during training

            # If the user sent the abort command, terminates the training early.
            if runtime.terminated:
                message = (
                    "Run training abort signal detected. Aborting the lick training with a graceful shutdown "
                    "procedure..."
                )
                console.echo(message=message, level=LogLevel.ERROR)
                break  # Breaks the for loop

            # Determines how many times the speed and duration thresholds have been increased based on the difference
            # between the total delivered water volume and the increase threshold. This dynamically adjusts the running
            # speed and duration thresholds with delivered water volume, ensuring the animal has to try progressively
            # harder to keep receiving water.
            increase_steps: np.float64 = np.floor(runtime.dispensed_water_volume / water_threshold)

            # Determines the speed and duration thresholds for each cycle. This factors in the user input via the
            # runtime control GUI. Note, user input has a static resolution of 0.01 cm/s and 0.01 s (10 ms) per step.
            speed_threshold: np.float64 = np.clip(
                a=initial_speed + (increase_steps * speed_step) + (runtime.speed_modifier * 0.01),
                a_min=0.1,  # Minimum value
                a_max=maximum_speed,  # Maximum value
            )
            duration_threshold: np.float64 = np.clip(
                a=initial_duration + (increase_steps * duration_step) + (runtime.duration_modifier * 10),
                a_min=50,  # Minimum value (0.05 seconds == 50 milliseconds)
                a_max=maximum_duration,  # Maximum value
            )

            # If any of the threshold changed relative to the previous loop iteration, updates the visualizer and
            # previous threshold trackers with new data. The update is forced at the beginning of runtime to make
            # the visualizer render the threshold lines and values.
            if once or (
                duration_threshold != previous_duration_threshold or previous_speed_threshold != speed_threshold
            ):
                runtime.update_visualizer_thresholds(speed_threshold, duration_threshold)
                previous_speed_threshold = speed_threshold
                previous_duration_threshold = duration_threshold

                # Inactivates the 'once' tracker after the first update.
                if once:
                    once = False

            # If the speed is above the speed threshold, and the animal has been maintaining the above-threshold speed
            # for the required duration, delivers 5 uL of water. If the speed is above the threshold, but the animal has
            # not yet maintained the required duration, the loop keeps cycling and accumulating the timer count.
            # This is done until the animal either reaches the required duration or drops below the speed threshold.
            if runtime.running_speed >= speed_threshold and running_duration_timer.elapsed >= duration_threshold:
                # Delivers 5 uL of water or simulates reward delivery. The method returns True if the reward was
                # delivered and False otherwise.
                if runtime.resolve_reward(reward_size=5.0):
                    # Updates the progress bar whenever the animal receives automated water rewards. The progress bar
                    # purposefully does not track 'manual' water rewards.
                    progress_bar.update(0.005)  # 5 uL == 0.005 ml

                # Also resets the timer. While mice typically stop consuming water rewards, which would reset the
                # timer, this guards against animals that carry on running without consuming water rewards.
                running_duration_timer.reset()

                # If the epoch timer was active for the current epoch, resets the timer
                epoch_timer_engaged = False

            # If the current speed is below the speed threshold, acts depending on whether the runtime is configured to
            # allow dipping below the threshold
            elif runtime.running_speed < speed_threshold:
                # If the user did not allow dipping below the speed threshold, resets the run duration timer.
                if maximum_idle_time == 0:
                    running_duration_timer.reset()

                # If the user has enabled brief dips below the speed threshold, starts the epoch timer to ensure the
                # animal recovers the speed in the allotted time.
                elif not epoch_timer_engaged:
                    epoch_timer.reset()
                    epoch_timer_engaged = True

                # If epoch timer is enabled, checks whether the animal has failed to recover its running speed in time.
                # If so, resets the run duration timer.
                elif epoch_timer.elapsed >= maximum_idle_time:
                    running_duration_timer.reset()
                    epoch_timer_engaged = False

            # If the animal is maintaining the required speed and the epoch timer was activated by the animal dipping
            # below the speed threshold, deactivates the timer. This is essential for ensuring the 'step discount'
            # time is applied to each case of speed dipping below the speed threshold, rather than the entire run epoch.
            elif (
                epoch_timer_engaged
                and runtime.running_speed >= speed_threshold
                and running_duration_timer.elapsed < duration_threshold
            ):
                epoch_timer_engaged = False

            # Updates the time display when each second passes. This updates the 'suffix' of the progress bar to keep
            # track of elapsed training time. Accounts for any additional time spent in the 'paused' state.
            elapsed_time = runtime_timer.elapsed - runtime.paused_time
            if elapsed_time > previous_time:
                previous_time = elapsed_time  # Updates previous time

                # Updates the time display without advancing the progress bar
                elapsed_minutes = int(elapsed_time // 60)
                elapsed_seconds = int(elapsed_time % 60)
                progress_bar.set_postfix_str(
                    f"Time: {elapsed_minutes:02d}:{elapsed_seconds:02d}/{maximum_training_time:02d}:00"
                )

                # Refreshes the display to show updated time without changing progress
                progress_bar.refresh()

            # If the total volume of water dispensed during runtime exceeds the maximum allowed volume, aborts the
            # training early with a success message.
            if runtime.dispensed_water_volume >= maximum_volume:
                message = (
                    f"Run training has delivered the maximum allowed volume of water ({maximum_volume} uL). Aborting "
                    f"the training process..."
                )
                console.echo(message=message, level=LogLevel.SUCCESS)
                break

        # Closes the progress bar if runtime ends as expected
        progress_bar.close()

    # RecursionErrors should not be raised by any runtime component except in the case that the user wants to terminate
    # the runtime as part of the startup checkpoint. Therefore, silences the error.
    except RecursionError:
        pass

    # Ensures that the function always attempts the graceful shutdown procedure, even if it encounters runtime errors.
    finally:
        # If the runtime was initialized, attempts to gracefully terminate runtime assets
        if runtime is not None:
            runtime.stop()

        # If the session runtime terminates before the session was initialized, removes session data from all
        # sources before shutting down.
        if session_data.raw_data.nk_path.exists():
            message = (
                "The runtime was unexpectedly terminated before it was able to initialize and start all assets. "
                "Removing all leftover data from the uninitialized session from all destinations..."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            purge_session(session_data)

        message = "Run training runtime: Complete."
        console.echo(message=message, level=LogLevel.SUCCESS)


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
    message = f"Initializing {experiment_name} experiment runtime..."
    console.echo(message=message, level=LogLevel.INFO)

    # Queries the data acquisition system runtime parameters
    system_configuration = get_system_configuration()

    # Verifies that the target project exists
    project_directory = system_configuration.paths.root_directory.joinpath(project_name)
    if not project_directory.exists():
        message = (
            f"Unable to execute the {experiment_name} experiment for the animal {animal_id} of project {project_name}. "
            f"The target project does not exist on the local machine. Use the 'sl-create-project' command to create "
            f"the project before running training or experiment sessions."
        )
        console.error(message=message, error=FileNotFoundError)

    # Prevents the user from executing the runtime if the project is not configured to run the requested experiment
    project_experiments = get_project_experiments(project=project_name)
    if experiment_name not in project_experiments:
        message = (
            f"Unable to execute the {experiment_name} experiment for the animal {animal_id} of project {project_name}. "
            f"The target project does not have an experiment configuration file named after the target experiment. Use "
            f"the 'sl-create-experiment' command to create the experiment before rerunning the experiment session."
        )
        console.error(message=message, error=FileNotFoundError)

    # These checks have been added in version 4.0.0 to help users abide by the 'one animal one project' policy. Now all
    # runtimes require each animal to be assigned to a single project.
    animal_projects = get_animal_project(animal_id=animal_id)
    if len(animal_projects) > 1:  # Rare case, often indicative of old migration pipeline use
        message = (
            f"Unable to execute the {experiment_name} experiment for the animal {animal_id} of project {project_name}. "
            f"The animal is associated with multiple projects on the local machine, which is not allowed. Remove the "
            f"animal from all extra projects and rerun the experiment."
        )
        console.error(message=message, error=ValueError)
    elif len(animal_projects) == 1 and animal_projects[0] != project_name:  # This indicates user error
        message = (
            f"Unable to execute the {experiment_name} experiment for the animal {animal_id} and project "
            f"{project_name}. The animal is already associated with a different project '{animal_projects[0]}'. Either "
            f"adjust the project name to match the animal's current project or use the 'sl-migrate-animal' CLI command "
            f"to first migrate the animal to the desired project and rerun the experiment."
        )
        console.error(message=message, error=ValueError)

    # Queries the current Python and library version information. This is then used to initialize the SessionData
    # instance.
    python_version, library_version = get_version_data()

    # Initializes data-management classes for the runtime. Note, SessionData creates the necessary session directory
    # hierarchy as part of this initialization process
    session_data = SessionData.create(
        project_name=project_name,
        animal_id=animal_id,
        session_type=SessionTypes.MESOSCOPE_EXPERIMENT,
        experiment_name=experiment_name,
        python_version=python_version,
        sl_experiment_version=library_version,
    )

    # Uses initialized SessionData instance to load the experiment configuration data
    experiment_config: MesoscopeExperimentConfiguration = MesoscopeExperimentConfiguration.from_yaml(
        file_path=session_data.raw_data.experiment_configuration_path
    )

    # Verifies that all Mesoscope-VR states used during experiments are valid
    valid_states = {1, 2}
    state: MesoscopeExperimentState
    for state in experiment_config.experiment_states.values():
        if state.system_state_code not in valid_states:
            message = (
                f"Invalid Mesoscope-VR system state code {state.system_state_code} encountered when verifying "
                f"{experiment_name} experiment configuration. Currently, only codes 1 (rest) and 2 (run) are supported "
                f"for the Mesoscope-VR system."
            )
            console.error(message=message, error=ValueError)

    # Initializes the timer to enforce experiment state durations
    runtime_timer = PrecisionTimer(precision=TimerPrecisions.SECOND)

    # Generates the session descriptor class
    descriptor = MesoscopeExperimentDescriptor(
        experimenter=experimenter,
        mouse_weight_g=animal_weight,
        dispensed_water_volume_ml=0.0,
        maximum_unconsumed_rewards=maximum_unconsumed_rewards,
    )

    runtime: _MesoscopeVRSystem | None = None
    try:
        # Initializes the runtime class
        runtime = _MesoscopeVRSystem(
            session_data=session_data, session_descriptor=descriptor, experiment_configuration=experiment_config
        )

        # Verifies that the Water Restriction log and the Surgery log Google Sheets are accessible. To do so,
        # instantiates both classes to run through the init checks. The classes are later re-instantiated during
        # session data preprocessing
        _ = WaterLog(
            animal_id=int(animal_id),
            session_date=session_data.session_name,
            credentials_path=system_configuration.paths.google_credentials_path,
            sheet_id=system_configuration.sheets.water_log_sheet_id,
        )
        _ = SurgeryLog(
            project_name=project_name,
            animal_id=int(animal_id),
            credentials_path=system_configuration.paths.google_credentials_path,
            sheet_id=system_configuration.sheets.surgery_sheet_id,
        )

        # Initializes all runtime assets and guides the user through hardware-specific runtime preparation steps.
        runtime.start()

        # If the user chose to terminate the runtime during initialization checkpoint, raises an error to jump to the
        # shutdown runtime sequence, bypassing all other runtime preparation steps.
        if runtime.terminated:
            # Note, this specific type of errors should not be raised by any other runtime component. Therefore, it is
            # possible to handle this type of exceptions as a unique marker for early user-requested runtime
            # termination.
            message = "The runtime was terminated early due to user request."
            console.echo(message=message, level=LogLevel.SUCCESS)
            raise RecursionError

        # Marks the session as fully initialized. This prevents session data from being automatically removed by
        # 'purge' runtimes.
        session_data.runtime_initialized()

        # Main runtime loop. It loops over all submitted experiment states and ends the runtime after executing the last
        # state
        for state in experiment_config.experiment_states.values():
            runtime_timer.reset()  # Resets the timer

            # Sets the Experiment state
            runtime.change_runtime_state(state.experiment_state_code)

            # Resets the tracker used to update the progress bar every second
            previous_seconds = 0

            # Resolves and sets the Mesoscope-VR system state
            if state.system_state_code == 1:
                runtime.rest()
            elif state.system_state_code == 2:
                runtime.run()

            # Configures the lick guidance parameters for the executed experiment state (stage).
            runtime.setup_lick_guidance(
                initial_guided_trials=state.initial_guided_trials,
                failed_trials_threshold=state.recovery_failed_trial_threshold,
                recovery_guided_trials=state.recovery_guided_trials,
            )

            # Creates a tqdm progress bar for the current experiment state
            with tqdm(
                total=state.state_duration_s,
                desc=f"Executing experiment state {state.experiment_state_code}",
                bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt}s",
            ) as pbar:
                # Cycles until the state duration of seconds passes
                while runtime_timer.elapsed < (state.state_duration_s + runtime.paused_time):
                    # Since experiment logic is resolved by the Unity game engine, the runtime logic function only
                    # needs to call the runtime cycle and handle termination and animal performance issue cases.
                    runtime.runtime_cycle()  # Repeatedly calls the runtime cycle as part of the experiment state cycle

                    # If the user has terminated the runtime, breaks the while loop. The termination is also handled at
                    # the level of the 'for' loop. The error message is generated at that level, rather than here.
                    if runtime.terminated:
                        break

                    # Updates the progress bar every second. Note, this calculation statically discounts the time spent
                    # in the paused state.
                    delta_seconds = runtime_timer.elapsed - (previous_seconds + runtime.paused_time)
                    if delta_seconds > 0:
                        # While it is unlikely that delta ever exceeds 1, supports this rare case
                        pbar.update(delta_seconds)
                        previous_seconds = runtime_timer.elapsed - runtime.paused_time

                runtime.paused_time = 0  # Resets the paused time before entering the next experiment state's cycle

                # If the user sent the abort command, terminates the experiment early.
                if runtime.terminated:
                    message = (
                        "Experiment runtime abort signal detected. Aborting the experiment with a graceful shutdown "
                        "procedure..."
                    )
                    console.echo(message=message, level=LogLevel.ERROR)
                    break  # Breaks the for loop

    # RecursionErrors should not be raised by any runtime component except in the case that the user wants to terminate
    # the runtime as part of the startup checkpoint. Therefore, silences the error.
    except RecursionError:
        pass

    # Ensures that the function always attempts the graceful shutdown procedure, even if it encounters runtime errors.
    finally:
        # If the runtime was initialized, attempts to gracefully terminate runtime assets
        if runtime is not None:
            runtime.stop()

        # If the session runtime terminates before the session was initialized, removes session data from all
        # sources before shutting down.
        if session_data.raw_data.nk_path.exists():
            message = (
                "The runtime was unexpectedly terminated before it was able to initialize and start all assets. "
                "Removing all leftover data from the uninitialized session from all destinations..."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            purge_session(session_data)

        message = "Experiment runtime: Complete."
        console.echo(message=message, level=LogLevel.SUCCESS)


def window_checking_logic(
    experimenter: str,
    project_name: str,
    animal_id: str,
) -> None:
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
    message = "Initializing window checking runtime..."
    console.echo(message=message, level=LogLevel.INFO)

    # Queries the data acquisition system runtime parameters.
    system_configuration = get_system_configuration()

    # Verifies that the target project exists
    project_directory = system_configuration.paths.root_directory.joinpath(project_name)
    if not project_directory.exists():
        message = (
            f"Unable to execute the window checking for the animal {animal_id} of project {project_name}. The target "
            f"project does not exist on the local machine. Use the 'sl-create-project' command to create the project "
            f"before running training or experiment sessions."
        )
        console.error(message=message, error=FileNotFoundError)

    # These checks have been added in version 4.0.0 to help users abide by the 'one animal one project' policy. Now all
    # runtimes require each animal to be assigned to a single project.
    animal_projects = get_animal_project(animal_id=animal_id)
    if len(animal_projects) > 1:  # Rare case, often indicative of old migration pipeline use
        message = (
            f"Unable to execute the window checking for the animal {animal_id} of project {project_name}. "
            f"The animal is associated with multiple projects on the local machine, which is not allowed. Remove the "
            f"animal from all extra projects and rerun the window checking."
        )
        console.error(message=message, error=ValueError)
    elif len(animal_projects) == 1 and animal_projects[0] != project_name:  # This indicates user error
        message = (
            f"Unable to execute the window checking for the animal {animal_id} and project "
            f"{project_name}. The animal is already associated with a different project '{animal_projects[0]}'. Either "
            f"adjust the project name to match the animal's current project or use the 'sl-migrate-animal' CLI command "
            f"to first migrate the animal to the desired project and rerun the window checking."
        )
        console.error(message=message, error=ValueError)

    # Queries the current Python and library version information. This is then used to initialize the SessionData
    # instance.
    python_version, library_version = get_version_data()

    # Generates the WindowCheckingDescriptor instance, caches it to disk, and forces the user to update the data
    # in the descriptor file with their notes.
    descriptor = WindowCheckingDescriptor(
        experimenter=experimenter,
        incomplete=True,
    )

    # Initializes data-management classes for the runtime. Note, SessionData creates the necessary session directory
    # hierarchy as part of this initialization process
    session_data = SessionData.create(
        project_name=project_name,
        animal_id=animal_id,
        session_type=SessionTypes.WINDOW_CHECKING,
        python_version=python_version,
        sl_experiment_version=library_version,
    )
    mesoscope_data = MesoscopeData(session_data=session_data, system_configuration=system_configuration)
    # Caches descriptor file precursor to disk before starting the main runtime. This is consistent with the behavior of
    # all other runtime functions.
    descriptor.to_yaml(file_path=session_data.raw_data.session_descriptor_path)

    # Generates and caches the MesoscopePositions precursor file to the persistent and raw_data directories.
    precursor = MesoscopePositions()
    precursor.to_yaml(file_path=session_data.raw_data.mesoscope_positions_path)
    precursor.to_yaml(file_path=mesoscope_data.vrpc_data.mesoscope_positions_path)

    zaber_motors: ZaberMotors | None = None
    try:
        # Establishes communication with Zaber motors
        zaber_motors = ZaberMotors(zaber_positions_path=mesoscope_data.vrpc_data.zaber_positions_path)

        message = "Initializing interface classes..."
        console.echo(message=message, level=LogLevel.INFO)

        # Initializes the data logger. This initialization follows the same procedure as the _MesoscopeVRSystem class
        logger: DataLogger = DataLogger(
            output_directory=session_data.raw_data.raw_data_path,
            instance_name="behavior",  # Creates behavior_log subdirectory under raw_data
            thread_count=10,
        )
        logger.start()

        # Initializes the face camera. Body cameras are not used during window checking.
        cameras = VideoSystems(data_logger=logger, output_directory=session_data.raw_data.camera_data_path)
        cameras.start_face_camera()
        message = "Face camera display: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

        # While we can connect to ports managed by ZaberLauncher, ZaberLauncher cannot connect to ports managed via
        # software. Therefore, we have to make sure ZaberLauncher is running before connecting to motors.
        message = (
            "Preparing to connect to all Zaber motor controllers. Make sure that ZaberLauncher app is running before "
            "proceeding further. If ZaberLauncher is not running, you WILL NOT be able to manually control Zaber motor "
            "positions until you reset the runtime."
        )
        console.echo(message=message, level=LogLevel.WARNING)
        input("Enter anything to continue: ")

        # Removes the nk.bin marker to avoid automatic session cleanup during post-processing.
        session_data.runtime_initialized()

        # Prepares Zaber motors for data acquisition.
        _setup_zaber_motors(zaber_motors=zaber_motors)

        # Runs the user through the process of preparing the mesoscope and assessing the quality of the animal's cranial
        # window.
        _setup_mesoscope(session_data=session_data, mesoscope_data=mesoscope_data)

        # noinspection PyTypeChecker
        # Instructs the user to update the session descriptor file
        _verify_descriptor_update(descriptor=descriptor, session_data=session_data, mesoscope_data=mesoscope_data)

        # Generates the snapshot of the Mesoscope imaging position used to generate the data during window checking.
        _generate_mesoscope_position_snapshot(session_data=session_data, mesoscope_data=mesoscope_data)

        # Retrieves current motor positions and packages them into a ZaberPositions object.
        _generate_zaber_snapshot(session_data=session_data, mesoscope_data=mesoscope_data, zaber_motors=zaber_motors)

        # Resets Zaber motors to their original positions.
        _reset_zaber_motors(zaber_motors=zaber_motors)

        # Terminates the face camera
        cameras.stop()

        # Stops the data logger
        logger.stop()

        # Triggers preprocessing pipeline. In this case, since there is no data to preprocess, the pipeline primarily
        # just copies the session raw_data directory to the NAS and BioHPC server. Unlike other pipelines, window
        # checking does not give the user a choice. All window checking data is necessarily preprocessed.
        preprocess_session_data(session_data=session_data)

    finally:
        # If the session runtime terminates before the session was initialized, removes session data from all sources
        # before shutting down.
        if session_data.raw_data.nk_path.exists():
            message = (
                "The runtime was unexpectedly terminated before it was able to initialize and start all assets. "
                "Removing all leftover data from the uninitialized session from all destinations..."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            purge_session(session_data)

        # If Zaber motors were connected, attempts to gracefully shut down the motors.
        if zaber_motors is not None:
            _reset_zaber_motors(zaber_motors=zaber_motors)

        # Ends the runtime
        message = "Window checking runtime: Complete."
        console.echo(message=message, level=LogLevel.SUCCESS)


def maintenance_logic() -> None:
    """Encapsulates the logic used to maintain a subset of the Mesoscope-VR system's hardware components."""
    console.echo(message="Initializing Mesoscope-VR system maintenance runtime...", level=LogLevel.INFO)

    # Queries the data acquisition system runtime parameters
    system_configuration = get_system_configuration()

    # Initializes a timer used to optimize the main runtime cycling.
    delay_timer = PrecisionTimer(precision=TimerPrecisions.MILLISECOND)

    # Determines whether to move all Zaber motors to the predefined maintenance positions.
    console.echo(
        message="Do you want to position the managed Zaber motors for valve calibration or referencing procedure?",
        level=LogLevel.INFO,
    )
    move_zaber_motors = ""
    while move_zaber_motors not in ["y", "n"]:
        move_zaber_motors = input("Enter 'yes' or 'no': ").lower()[0]

    # All calibration procedures are executed in a temporary directory deleted after runtime
    with tempfile.TemporaryDirectory(prefix="sl_maintenance_") as output_dir:
        try:
            console.echo(message="Initializing the maintenance assets...", level=LogLevel.INFO)

            # Initializes the data logger. All log entries recorded by the logger during runtime are discarded at the
            # end of runtime, hence the name 'temporary'.
            logger = DataLogger(
                output_directory=Path(output_dir),
                instance_name="temporary",
                thread_count=10,
            )
            logger.start()

            # Initializes the interface for the Actor MicroController.
            valve: ValveInterface = ValveInterface(
                valve_calibration_data=system_configuration.microcontrollers.valve_calibration_data,
            )
            wheel: BrakeInterface = BrakeInterface(
                minimum_brake_strength=system_configuration.microcontrollers.minimum_brake_strength_g_cm,
                maximum_brake_strength=system_configuration.microcontrollers.maximum_brake_strength_g_cm,
            )
            controller: MicroControllerInterface = MicroControllerInterface(
                controller_id=np.uint8(101),
                buffer_size=8192,
                port=system_configuration.microcontrollers.actor_port,
                data_logger=logger,
                module_interfaces=(valve, wheel),
            )
            controller.start()

            message = "Actor MicroController interface: Initialized."
            console.echo(message=message, level=LogLevel.SUCCESS)

            # Avoids the visual clash with the Zaber positioning dialog.
            _response_delay_timer.delay(delay=_RENDERING_SEPARATION_DELAY, block=False)

            # If Zaber motors are being used, initializes and moves them to the maintenance positions.
            if move_zaber_motors == "y":
                message = "Initializing Zaber motors..."
                console.echo(message=message, level=LogLevel.INFO)
                zaber_motors: ZaberMotors = ZaberMotors(
                    zaber_positions=None, zaber_configuration=system_configuration.assets
                )
                message = (
                    "Preparing to move Zaber motors to their maintenance positions. Remove the mesoscope objective, "
                    "swivel out the VR screens, and make sure the animal is NOT mounted on the rig. Failure to fulfill "
                    "these steps may DAMAGE the mesoscope and / or HARM the animal."
                )
                console.echo(message=message, level=LogLevel.WARNING)

                # Delays to ensure the user reads the message before continuing.
                _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)

                input("Press Enter to continue: ")
                zaber_motors.prepare_motors()
                zaber_motors.maintenance_position()

                message = "Zaber motors: Positioned for Mesoscope-VR system maintenance."
                console.echo(message=message, level=LogLevel.SUCCESS)

            # Initializes the maintenance GUI
            # noinspection PyProtectedMember
            ui = MaintenanceControlUI(valve_tracker=valve._valve_tracker)  # Directly access the module's tracker.
            ui.start()

            # Notifies the user that the runtime is initialized.
            console.echo(
                message="Maintenance runtime: Initialized. Use the GUI to control the valve and brake.",
                level=LogLevel.SUCCESS,
            )

            # Enters the main control loop, relinquishing control to the maintenance GUI.
            while not ui.exit_signal:
                # Opens the valve
                if ui.valve_open_signal:
                    valve.set_state(state=True)

                # Closes the valve
                if ui.valve_close_signal:
                    valve.set_state(state=False)

                # Uses the valve to deliver a water reward
                if ui.valve_reward_signal:
                    valve.deliver_reward(volume=float(ui.reward_volume))

                # References the valve
                if ui.valve_reference_signal:
                    valve.reference_valve()

                # Performs the valve calibration procedure
                if ui.valve_calibrate_signal:
                    valve.calibrate_valve(pulse_duration=ui.calibration_pulse_duration)

                # Locks the wheel brake
                if ui.brake_lock_signal:
                    wheel.set_state(state=True)

                # Unlocks the wheel brake
                if ui.brake_unlock_signal:
                    wheel.set_state(state=False)

                # Delays for 5 milliseconds to avoid busy-waiting
                delay_timer.delay(delay=5, block=False)

        # Ensures that the runtime always attempts to terminate all assets gracefully
        finally:
            message = "Terminating Mesoscope-VR maintenance runtime..."
            console.echo(message=message, level=LogLevel.INFO)

            # If Zaber motors were used and are still connected, moves them to the park position.
            if move_zaber_motors == "y" and zaber_motors is not None and zaber_motors.is_connected:
                message = (
                    "Preparing to reset all Zaber motors. Remove all objects used during Mesoscope-VR maintenance, "
                    "such as water collection flasks, from the Mesoscope-VR cage."
                )
                console.echo(message=message, level=LogLevel.WARNING)

                # Delays for 2 seconds to ensure the user reads the message before continuing.
                _response_delay_timer.delay(delay=_RESPONSE_DELAY, block=False)

                input("Press Enter to continue: ")
                zaber_motors.park_position()
                zaber_motors.disconnect()

            # Shuts down the actor microcontroller interface.
            if controller is not None:
                controller.stop()

                message = "Actor MicroController interface: Terminated."
                console.echo(message=message, level=LogLevel.SUCCESS)

            # Stops the data logger
            if logger is not None:
                logger.stop()

            # Shuts down the UI
            if ui is not None:
                ui.shutdown()

            message = "Mesoscope-VR system maintenance runtime: Terminated."
            console.echo(message=message, level=LogLevel.SUCCESS)
