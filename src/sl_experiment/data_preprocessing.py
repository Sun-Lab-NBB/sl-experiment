"""This module provides the methods used to preprocess experimental data after acquisition. The primary purpose of this
procedure is to prepare the data for storage and further processing in the Sun lab data cluster.

This module also provides some of the dataclasses used to store runtime information on disk (session descriptors,
hardware configuration) and the main SessionData class used to manage the data of each session.
"""

import os
import json
import time
import shutil as sh
from typing import Any
from pathlib import Path
from datetime import datetime
import warnings
from functools import partial
from collections import defaultdict
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

from tqdm import tqdm
import numpy as np
import tifffile
from numpy.typing import NDArray
from ataraxis_base_utilities import LogLevel, console, ensure_directory_exists
from ataraxis_data_structures import YamlConfig, compress_npy_logs
from ataraxis_time.time_helpers import get_timestamp

from .transfer_tools import transfer_directory
from .packaging_tools import calculate_directory_checksum
from .google_sheet_tools import SurgeryData, SurgerySheet, WaterSheetData


# Most of these classes have to be defined here to avoid circular import in experiment.py
@dataclass()
class RuntimeHardwareConfiguration(YamlConfig):
    """This class is used to save the runtime hardware configuration information as a .yaml file.

    This information is used to read the data saved to the .npz log files during runtime during data processing.

    Notes:
        All fields in this dataclass initialize to None. During log processing, any log associated with a hardware
        module that provides the data stored in a field will be processed, unless that field is None. Therefore, setting
        any field in this dataclass to None also functions as a flag for whether to parse the log associated with the
        module that provides this field's information.

        This class is automatically configured by MesoscopeExperiment and BehaviorTraining classes to facilitate log
        parsing.
    """

    cue_map: dict[int, float] | None = None
    """MesoscopeExperiment instance property."""
    cm_per_pulse: float | None = None
    """EncoderInterface instance property."""
    maximum_break_strength: float | None = None
    """BreakInterface instance property."""
    minimum_break_strength: float | None = None
    """BreakInterface instance property."""
    lick_threshold: int | None = None
    """BreakInterface instance property."""
    scale_coefficient: float | None = None
    """ValveInterface instance property."""
    nonlinearity_exponent: float | None = None
    """ValveInterface instance property."""
    torque_per_adc_unit: float | None = None
    """TorqueInterface instance property."""
    initially_on: bool | None = None
    """ScreenInterface instance property."""
    has_ttl: bool | None = None
    """TTLInterface instance property."""


@dataclass
class SessionData(YamlConfig):
    """Provides methods for managing the data acquired during one experiment or training session.

    This class functions as the central hub for collecting the data from all local PCs involved in the data acquisition
    process and pushing it to the NAS and the BioHPC server. Its primary purpose is to maintain the session data
    structure across all supported destinations and to efficiently and safely move the data to these destinations with
    minimal redundancy and footprint. Additionally, this class generates the paths used by all other classes from
    this library to determine where to load and saved various data during runtime. Finally, it also carries out basic
    data preprocessing to optimize raw data for network transmission and long-term storage.

    As part of its initialization, the class generates the session directory for the input animal and project
    combination. Session directories use the current UTC timestamp, down to microseconds, as the directory name. This
    ensures that each session name is unique and preserves the overall session order.

    Notes:
        Do not call methods from this class directly. This class is intended to be used primarily through the runtime
        logic functions from the experiment.py module and general command-line-interfaces installed with the library.
        The only reason the class is defined as public is to support reconfiguring data destinations and session details
        when implementing custom CLI functions for projects that use this library.

        It is expected that the server, NAS, and mesoscope data directories are mounted on the host-machine via the
        SMB or equivalent protocol. All manipulations with these destinations are carried out with the assumption that
        the OS has full access to these directories and filesystems.

        This class is specifically designed for working with raw data from a single animal participating in a single
        experimental project session. Processed data is managed by the processing library methods and classes.

        This class generates an xxHash-128 checksum stored inside the ax_checksum.txt file at the root of each
        experimental session 'raw_data' directory. The checksum verifies the data of each file and the paths to each
        file relative to the 'raw_data' root directory.
    """

    # Main attributes that are expected to be provided by the user during class initialization
    project_name: str
    """The name of the project for which the data is acquired."""
    animal_id: str
    """The ID code of the animal for which the data is acquired."""
    surgery_sheet_id: str
    """The ID for the Google Sheet file that stores surgery information for the animal whose data is managed by this 
    instance. This is used to parse and write the surgery data for each managed animal into its 'metadata' folder, so 
    that the surgery data is always kept together with the rest of the training and experiment data."""
    water_log_sheet_id: str
    """The ID for the Google Sheet file that stores water restriction information for the animal whose data is managed 
    by this instance. This is used to synchronize the information inside the water restriction log with the state of 
    the animal at the end of each training or experiment runtime.
    """
    session_type: str
    """Stores the type of the session. Primarily, this determines how to read the session_descriptor.yaml file. Has 
    to be set to one of the three supported types: 'lick_training', 'run_training' or 'experiment'.
    """
    credentials_path: str = "/media/Data/Experiments/sl-surgery-log-0f651e492767.json"
    """
    The path to the locally stored .JSON file that stores the service account credentials used to read and write Google 
    Sheet data. This is used to access and work with the surgery log and the water restriction log.
    """
    local_root_directory: str = "/media/Data/Experiments"
    """The path to the root directory where all projects are stored on the host-machine (VRPC)."""
    server_root_directory: str = "/media/cbsuwsun/storage/sun_data"
    """The path to the root directory where all projects are stored on the BioHPC server machine."""
    nas_root_directory: str = "/home/cybermouse/nas/rawdata"
    """The path to the root directory where all projects are stored on the Synology NAS."""
    mesoscope_root_directory: str = "/home/cybermouse/scanimage/mesodata"
    """The path to the root directory used to store all mesoscope-acquired data on the ScanImagePC."""
    session_name: str = "None"
    """Stores the name of the session for which the data is acquired. This name is generated at class initialization 
    based on the current microsecond-accurate timestamp. Do NOT manually provide this name at class initialization.
    Use 'from_path' class method to initialize a SessionData instance for an already existing session data directory.
    """

    def __post_init__(self) -> None:
        """Generates the session name and creates the session directory structure on all involved PCs."""

        # If the session name is provided, ends the runtime early. This is here to support initializing the
        # SessionData class from the path to the root directory of a previous created session.
        if self.session_name is not None:
            return

        # Acquires the UTC timestamp to use as the session name
        self.session_name = str(get_timestamp(time_separator="-"))

        # Converts root strings to Path objects.
        local_root_directory = Path(self.local_root_directory)
        server_root_directory = Path(self.server_root_directory)
        nas_root_directory = Path(self.nas_root_directory)
        mesoscope_root_directory = Path(self.mesoscope_root_directory)

        # Constructs the session directory path and generates the directory
        raw_session_path = local_root_directory.joinpath(self.project_name, self.animal_id, self.session_name)

        # Handles potential session name conflicts
        counter = 0
        while raw_session_path.exists():
            counter += 1
            new_session_name = f"{self.session_name}_{counter}"
            raw_session_path = local_root_directory.joinpath(self.project_name, self.animal_id, new_session_name)

        # If a conflict is detected and resolved, warns the user about the resolved conflict.
        if counter > 0:
            message = (
                f"Session name conflict occurred for animal '{self.animal_id}' of project '{self.project_name}' "
                f"when adding the new session with timestamp {self.session_name}. The session with identical name "
                f"already exists. The newly created session directory uses a '_{counter}' postfix to distinguish "
                f"itself from the already existing session directory."
            )
            warnings.warn(message=message)

        # Saves the final session name to class attribute
        self.session_name = raw_session_path.stem

        # Generates the directory structures on all computers used in data management:
        # Raw Data directory and all subdirectories.
        ensure_directory_exists(
            local_root_directory.joinpath(self.project_name, self.animal_id, self.session_name, "raw_data")
        )
        ensure_directory_exists(
            local_root_directory.joinpath(
                self.project_name, self.animal_id, self.session_name, "raw_data", "camera_frames"
            )
        )
        ensure_directory_exists(
            local_root_directory.joinpath(
                self.project_name, self.animal_id, self.session_name, "raw_data", "mesoscope_frames"
            )
        )
        ensure_directory_exists(
            local_root_directory.joinpath(
                self.project_name, self.animal_id, self.session_name, "raw_data", "behavior_data_log"
            )
        )

        ensure_directory_exists(local_root_directory.joinpath(self.project_name, self.animal_id, "persistent_data"))
        ensure_directory_exists(nas_root_directory.joinpath(self.project_name, self.animal_id, self.session_name))
        ensure_directory_exists(server_root_directory.joinpath(self.project_name, self.animal_id, self.session_name))
        ensure_directory_exists(local_root_directory.joinpath(self.project_name, self.animal_id, "metadata"))
        ensure_directory_exists(server_root_directory.joinpath(self.project_name, self.animal_id, "metadata"))
        ensure_directory_exists(nas_root_directory.joinpath(self.project_name, self.animal_id, "metadata"))
        ensure_directory_exists(mesoscope_root_directory.joinpath("mesoscope_frames"))
        ensure_directory_exists(mesoscope_root_directory.joinpath("persistent_data", self.project_name, self.animal_id))

    @classmethod
    def from_path(cls, path: Path) -> "SessionData":
        """Initializes a SessionData instance to represent the data of an already existing session.

        Typically, this initialization mode is used to preprocess an interrupted session. This method uses the cached
        data stored in the 'session_data.yaml' file in the 'raw_data' subdirectory of the provided session directory.

        Args:
            path: The path to the session directory on the local (VRPC) machine.

        Returns:
            An initialized SessionData instance for the session whose data is stored at the provided path.

        Raises:
            FileNotFoundError: If the 'session_data.yaml' file is not found after resolving the provided path.
        """
        path = path.joinpath("raw_data", "session_data.yaml")

        if not path.exists():
            message = (
                f"No 'session_data.yaml' file found at the provided path: {path}. Unable to preprocess the target "
                f"session, as session_data.yaml is required to run preprocessing. This likely indicates that the "
                f"session runtime was interrupted before recording any data, as the session_data.yaml snapshot is "
                f"generated very early in the session runtime."
            )
            console.error(message=message, error=FileNotFoundError)

        return cls.from_yaml(file_path=path.joinpath("raw_data", "session_data.yaml"))  # type: ignore

    def to_path(self) -> None:
        """Saves the data of the instance to the 'raw_data' directory of the managed session as a 'session_data.yaml'
        file.

        This is used to save the data stored in the instance to disk, so that it can be reused during preprocessing or
        data processing. This also serves as the repository for the identification information about the project,
        animal, and session that generated the data.
        """
        self.to_yaml(file_path=self.raw_data_path.joinpath("session_data.yaml"))

    @property
    def raw_data_path(self) -> Path:
        """Returns the path to the 'raw_data' directory of the managed session on the VRPC.

        This directory functions as the root directory that stores all raw data acquired during training or experiment
        runtime for a given session.
        """
        local_root_directory = Path(self.local_root_directory)
        return local_root_directory.joinpath(self.project_name, self.animal_id, self.session_name, "raw_data")

    @property
    def camera_frames_path(self) -> Path:
        """Returns the path to the 'camera_frames' directory of the managed session.

        This subdirectory is stored under the 'raw_data' directory and aggregates all video camera data.
        """
        return self.raw_data_path.joinpath("camera_frames")

    @property
    def zaber_positions_path(self) -> Path:
        """Returns the path to the 'zaber_positions.yaml' file of the managed session.

        This path is used to save the positions for all Zaber motors of the HeadBar and LickPort controllers at the
        end of the experimental session.
        """
        return self.raw_data_path.joinpath("zaber_positions.yaml")

    @property
    def session_descriptor_path(self) -> Path:
        """Returns the path to the 'session_descriptor.yaml' file of the managed session.

        This path is used to save important session information to be viewed by experimenters post-runtime and to use
        for further processing.
        """
        return self.raw_data_path.joinpath("session_descriptor.yaml")

    @property
    def hardware_configuration_path(self) -> Path:
        """Returns the path to the 'hardware_configuration.yaml' file of the managed session.

        This file stores hardware module parameters used to read and parse .npz log files during data processing.
        """
        return self.raw_data_path.joinpath("hardware_configuration.yaml")

    @property
    def previous_zaber_positions_path(self) -> Path:
        """Returns the path to the 'zaber_positions.yaml' file of the previous session.

        The file is stored inside the 'persistent_data' directory of the managed animal.
        """
        local_root_directory = Path(self.local_root_directory)
        return local_root_directory.joinpath(
            self.project_name, self.animal_id, "persistent_data", "zaber_positions.yaml"
        )

    @property
    def mesoscope_root_path(self) -> Path:
        """Returns the path to the root directory of the Mesoscope pc (ScanImagePC) used to store all
        mesoscope-acquired data.
        """
        return Path(self.mesoscope_root_directory)

    @property
    def nas_root_path(self) -> Path:
        """Returns the path to the root directory of the Synology NAS (Network Attached Storage) used to store all
        training and experiment data after preprocessing (backup cold long-term storage)."""
        return Path(self.nas_root_directory)

    @property
    def server_root_path(self) -> Path:
        """Returns the path to the root directory of the BioHPC server used to process and store all training and e
        experiment data (main long-term storage)."""
        return Path(self.server_root_directory)

    @property
    def mesoscope_persistent_path(self) -> Path:
        """Returns the path to the 'persistent_data' directory of the Mesoscope pc (ScanImagePC).

        This directory is primarily used to store the reference MotionEstimator.me files for each animal.
        """
        return self.mesoscope_root_path.joinpath("persistent_data", self.project_name, self.animal_id)

    @property
    def local_metadata_path(self) -> Path:
        """Returns the path to the 'metadata' directory of the managed animal on the VRPC."""
        local_root_directory = Path(self.local_root_directory)
        return local_root_directory.joinpath(self.project_name, self.animal_id, "metadata")

    @property
    def server_metadata_path(self) -> Path:
        """Returns the path to the 'metadata' directory of the managed animal on the BioHPC server."""
        return self.server_root_path.joinpath(self.project_name, self.animal_id, "metadata")

    @property
    def nas_metadata_path(self) -> Path:
        """Returns the path to the 'metadata' directory of the managed animal on the Synology NAS."""
        return self.nas_root_path.joinpath(self.project_name, self.animal_id, "metadata")

    def preprocess_session_data(self) -> None:
        """Carries out all data preprocessing tasks to prepare the data for NAS / BioHPC server transfer and future
        processing.

        This method should be called at the end of each training and experiment runtime to compress and safely transfer
        the data to its long-term storage destinations.

        Notes:
            The method will NOT delete the data from the VRPC or ScanImagePC. To safely remove the data, use the
            purge-redundant-data CLI command. The data will only be removed if it has been marked for removal by our
            data management algorithms, which ensure we have enough spare copies of the data elsewhere.
        """
        # Enables console, if it is not enabled
        if not console.enabled:
            console.enable()

        message = "Initializing data preprocessing..."
        console.echo(message=message, level=LogLevel.INFO)

        # If the instance manages a session that acquired mesoscope frames, renames the generic mesoscope_frames
        # directory to include the session name. It is essential that this is done before preprocessing, as
        # the preprocessing pipeline uses this semantic for finding and pulling the mesoscope data for the processed
        # session.
        general_path = self.mesoscope_root_path.joinpath("mesoscope_frames")
        session_specific_path = self.mesoscope_root_path.joinpath(f"{self.session_name}_mesoscope_frames")

        # Note, the renaming only happens if the session-specific cache does not exist, the general
        # mesoscope_frames cache exists, and it is not empty (has files inside).
        if (
            not session_specific_path.exists()
            and general_path.exists()
            and len([path for path in general_path.glob("*")]) > 0
        ):
            general_path.rename(session_specific_path)
            ensure_directory_exists(general_path)  # Generates a new empty mesoscope_frames directory

        # Compresses all log entries (.npy) into archive files (.npz)
        _preprocess_log_directory(session_data=self, num_processes=31, remove_sources=True, verify_integrity=False)

        # Renames all videos to use human-friendly names
        _preprocess_video_names(session_data=self)

        # Pulls mesoscope-acquired data from the ScanImagePC to the VRPC
        _pull_mesoscope_data(
            session_data=self,
            num_threads=31,
            remove_sources=True,
            verify_transfer_integrity=True,
        )

        # Compresses all mesoscope-acquired frames and extracts their metadata
        _preprocess_mesoscope_directory(
            session_data=self,
            num_processes=31,
            remove_sources=True,
            verify_integrity=True,
            batch_size=100,
        )

        # Extracts and saves the surgery data to the metadata directories and writes the water restriction log data
        # for the animal
        _preprocess_google_sheet_data(session_data=self)

        # Sends preprocessed data to the NAS and the BioHPC server
        _push_data(
            session_data=self,
            parallel=True,
            num_threads=15,
        )

        # Extracts adn saves animal surgery data and updates the water restriction log with animal runtime data.
        _preprocess_google_sheet_data(session_data=self)

        message = "Data preprocessing: Complete."
        console.echo(message=message, level=LogLevel.SUCCESS)


@dataclass()
class LickTrainingDescriptor(YamlConfig):
    """This class is used to save the description information specific to lick training sessions as a .yaml file."""

    experimenter: str
    """The ID of the experimenter running the session."""
    mouse_weight_g: float
    """The weight of the animal, in grams, at the beginning of the session."""
    dispensed_water_volume_ml: float = 0.0
    """Stores the total water volume, in milliliters, dispensed during runtime."""
    average_reward_delay_s: int = 12
    """Stores the center-point for the reward delay distribution, in seconds."""
    maximum_deviation_from_average_s: int = 6
    """Stores the deviation value, in seconds, used to determine the upper and lower bounds for the reward delay 
    distribution."""
    maximum_water_volume_ml: float = 1.0
    """Stores the maximum volume of water the system is allowed to dispense during training."""
    maximum_training_time_m: int = 40
    """Stores the maximum time, in minutes, the system is allowed to run the training for."""
    experimenter_notes: str = "Replace this with your notes."
    """This field is not set during runtime. It is expected that each experimenter will replace this field with their 
    notes made during runtime."""
    experimenter_given_water_volume_ml: float = 0.0
    """The additional volume of water, in milliliters, administered by the experimenter to the animal after the session.
    """


@dataclass()
class RunTrainingDescriptor(YamlConfig):
    """This class is used to save the description information specific to run training sessions as a .yaml file."""

    experimenter: str
    """The ID of the experimenter running the session."""
    mouse_weight_g: float
    """The weight of the animal, in grams, at the beginning of the session."""
    dispensed_water_volume_ml: float = 0.0
    """Stores the total water volume, in milliliters, dispensed during runtime."""
    final_running_speed_cm_s: float = 0.0
    """Stores the final running speed threshold that was active at the end of training."""
    final_speed_duration_s: float = 0.0
    """Stores the final running duration threshold that was active at the end of training."""
    initial_running_speed_cm_s: float = 0.0
    """Stores the initial running speed threshold, in centimeters per second, used during training."""
    initial_speed_duration_s: float = 0.0
    """Stores the initial above-threshold running duration, in seconds, used during training."""
    increase_threshold_ml: float = 0.0
    """Stores the volume of water delivered to the animal, in milliliters, that triggers the increase in the running 
    speed and duration thresholds."""
    increase_running_speed_cm_s: float = 0.0
    """Stores the value, in centimeters per second, used by the system to increment the running speed threshold each 
    time the animal receives 'increase_threshold' volume of water."""
    increase_speed_duration_s: float = 0.0
    """Stores the value, in seconds, used by the system to increment the duration threshold each time the animal 
    receives 'increase_threshold' volume of water."""
    maximum_running_speed_cm_s: float = 0.0
    """Stores the maximum running speed threshold, in centimeters per second, the system is allowed to use during 
    training."""
    maximum_speed_duration_s: float = 0.0
    """Stores the maximum above-threshold running duration, in seconds, the system is allowed to use during training."""
    maximum_water_volume_ml: float = 1.0
    """Stores the maximum volume of water the system is allowed to dispensed during training."""
    maximum_training_time_m: int = 40
    """Stores the maximum time, in minutes, the system is allowed to run the training for."""
    experimenter_notes: str = "Replace this with your notes."
    """This field is not set during runtime. It is expected that each experimenter will replace this field with their 
    notes made during runtime."""
    experimenter_given_water_volume_ml: float = 0.0
    """The additional volume of water, in milliliters, administered by the experimenter to the animal after the session.
    """


@dataclass()
class MesoscopeExperimentDescriptor(YamlConfig):
    """This class is used to save the description information specific to experiment sessions as a .yaml file."""

    experimenter: str
    """The ID of the experimenter running the session."""
    mouse_weight_g: float
    """The weight of the animal, in grams, at the beginning of the session."""
    dispensed_water_volume_ml: float = 0.0
    """Stores the total water volume, in milliliters, dispensed during runtime."""
    experimenter_notes: str = "Replace this with your notes."
    """This field is not set during runtime. It is expected that each experimenter will replace this field with their 
    notes made during runtime."""
    experimenter_given_water_volume_ml: float = 0.0
    """The additional volume of water, in milliliters, administered by the experimenter to the animal after the session.
    """


def _delete_directory(directory_path: Path) -> None:
    """Removes the input directory and all its subdirectories using parallel processing.

    This function outperforms default approaches like subprocess call with rm -rf and shutil rmtree for directories with
    a comparably small number of large files. For example, this is the case for the mesoscope frame directories, which
    are deleted ~6 times faster with this method over sh.rmtree. Potentially, it may also outperform these approaches
    for all comparatively shallow directories.

    Args:
        directory_path: The path to the directory to delete.
    """
    # Checks if the directory exists and, if not, aborts early
    if not directory_path.exists():
        return

    # Builds the list of files and directories inside the input directory using Path
    files = [p for p in directory_path.iterdir() if p.is_file()]
    subdirectories = [p for p in directory_path.iterdir() if p.is_dir()]

    # Deletes files in parallel
    with ThreadPoolExecutor() as executor:
        list(executor.map(os.unlink, files))  # Forces completion of all tasks\

    # Recursively deletes subdirectories
    for subdir in subdirectories:
        _delete_directory(subdir)

    # Removes the now-empty directory. Since Windows (ScanImagePC) is slow to release handles at some points, adds an
    # optional delay step to give Windows time to release file handles.
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            os.rmdir(directory_path)
            break  # Breaks early if the call succeeds
        except Exception:
            if attempt == max_attempts - 1:
                break  # Breaks after 5 attempts
            time.sleep(0.5)  # For each failed attempt, sleeps for 500 ms


def _get_stack_number(tiff_path: Path) -> int | None:
    """A helper function that determines the number of mesoscope-acquired tiff stacks using its file name.

    This is used to sort all TIFF stacks in a directory before recompressing them with LERC scheme. Like
    other helpers, this helper is also used to identify and remove non-mesoscope TIFFs from the dataset.
    """
    try:
        return int(tiff_path.stem.split("_")[-1])  # ScanImage appends _acquisition#_file# to files, we use file# here.
    except (ValueError, IndexError):
        return None  # This is used to filter non-ScanImage TIFFS


def _check_stack_size(file: Path) -> int:
    """Reads the header of the input TIFF file, and if the file is a stack, extracts its size.

    This function is used to both determine the stack size of the processed TIFF files and to exclude non-mesoscope
    TIFFs from processing.

    Notes:
        This function only works with monochrome TIFF stacks generated by the mesoscope. It expects each TIFF file to
        be a stack of 2D frames.

    Args:
        file: The path to the TIFF file to evaluate.

    Returns:
        If the file is a stack, returns the number of frames (pages) in the stack. Otherwise, returns 0 to indicate that
        the file is not a stack.
    """
    with tifffile.TiffFile(file) as tif:
        # Gets number of pages (frames) from tiff header
        n_frames = len(tif.pages)

        # Considers all files with more than one page and a 2-dimensional (monochrome) image as a stack. For these
        # stacks, returns the discovered stack size (number of frames). Also ensures that the files have the ScanImage
        # metadata. This latter step will exclude already processed BigTiff files.
        if n_frames > 1 and len(tif.pages[0].shape) == 2 and tif.scanimage_metadata is not None:
            return n_frames
        # Otherwise, returns 0 to indicate that the file is not a stack.
        return 0


def _process_stack(
    tiff_path: Path, first_frame_number: int, output_dir: Path, verify_integrity: bool, batch_size: int = 250
) -> dict[str, Any]:
    """Reads a TIFF stack, extracts its frame-variant ScanImage data, and saves it as a LERC-compressed stacked TIFF
    file.

    This is a worker function called by the process_mesoscope_directory in-parallel for each stack inside each
    processed directory. It re-compresses the input TIFF stack using LERC-compression and extracts the frame-variant
    ScanImage metadata for each frame inside the stack. Optionally, the function can be configured to verify data
    integrity after compression.

    Notes:
        This function can reserve up to double the processed stack size of RAM bytes to hold the data in memory. If the
        host-computer does not have enough RAM, reduce the number of concurrent processes, reduce the batch size, or
        disable verification.

    Raises:
        RuntimeError: If any extracted frame does not match the original frame stored inside the TIFF stack.
        NotImplementedError: If extracted frame-variant metadata contains unexpected keys or expected keys for which
            we do not have a custom extraction implementation.

    Args:
        tiff_path: The path to the TIFF stack to process.
        first_frame_number: The position (number) of the first frame stored in the stack, relative to the overall
            sequence of frames acquired during the experiment. This is used to configure the output file name to include
            the range of frames stored in the stack.
        output_dir: The path to the directory where to save the processed stacks.
        verify_integrity: Determines whether to verify the integrity of compressed data against the source data.
            The conversion does not alter the source data, so it is usually safe to disable this option, as the chance
            of compromising the data is negligible. Note, enabling this function doubles the RAM usage for each worker
            process.
        batch_size: The number of frames to process at the same time. This directly determines the RAM footprint of
            this function, as frames are kept in RAM during compression. Note, verification doubles the RAM footprint,
            as it requires both compressed and uncompressed data to be kept in RAM for comparison.
    """
    # Generates the file handle for the current stack
    with tifffile.TiffFile(tiff_path) as stack:
        # Determines the size of the stack
        stack_size = len(stack.pages)

        # Initializes arrays for storing metadata
        frame_nums = np.zeros(stack_size, dtype=np.int32)
        acq_nums = np.zeros(stack_size, dtype=np.int32)
        frame_num_acq = np.zeros(stack_size, dtype=np.int32)
        frame_timestamps = np.zeros(stack_size, dtype=np.float64)
        acq_trigger_timestamps = np.zeros(stack_size, dtype=np.float64)
        next_file_timestamps = np.zeros(stack_size, dtype=np.float64)
        end_of_acq = np.zeros(stack_size, dtype=np.int32)
        end_of_acq_mode = np.zeros(stack_size, dtype=np.int32)
        dc_over_voltage = np.zeros(stack_size, dtype=np.int32)
        epoch_timestamps = np.zeros(stack_size, dtype=np.uint64)

        # Loops over each page in the stack and extracts the metadata associated with each frame
        for i, page in enumerate(stack.pages):
            metadata = page.tags["ImageDescription"].value  # type: ignore

            # The metadata is returned as a 'newline'-delimited string of key=value pairs. This preprocessing header
            # splits the string into separate key=value pairs. Then, each pair is further separated and processed as
            # necessary
            for line in metadata.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # This section is geared to the output produced by the Sun Lab mesoscope. Any changes to the output
                # metadata will trigger an error and will require manual code adjustment to support parsing new
                # metadata tags. Each cycle updates the specific index of each output array with parsed data.
                if key == "frameNumbers":
                    frame_nums[i] = int(value)
                elif key == "acquisitionNumbers":
                    acq_nums[i] = int(value)
                elif key == "frameNumberAcquisition":
                    frame_num_acq[i] = int(value)
                elif key == "frameTimestamps_sec":
                    frame_timestamps[i] = float(value)
                elif key == "acqTriggerTimestamps_sec":
                    acq_trigger_timestamps[i] = float(value)
                elif key == "nextFileMarkerTimestamps_sec":
                    next_file_timestamps[i] = float(value)
                elif key == "endOfAcquisition":
                    end_of_acq[i] = int(value)
                elif key == "endOfAcquisitionMode":
                    end_of_acq_mode[i] = int(value)
                elif key == "dcOverVoltage":
                    dc_over_voltage[i] = int(value)
                elif key == "epoch":
                    # Parse epoch [year month day hour minute second.microsecond]
                    epoch_vals = [float(x) for x in value[1:-1].split()]
                    timestamp = int(
                        datetime(
                            int(epoch_vals[0]),
                            int(epoch_vals[1]),
                            int(epoch_vals[2]),
                            int(epoch_vals[3]),
                            int(epoch_vals[4]),
                            int(epoch_vals[5]),
                            int((epoch_vals[5] % 1) * 1e6),
                        ).timestamp()
                        * 1e6
                    )  # Convert to microseconds
                    epoch_timestamps[i] = timestamp
                elif key in ["auxTrigger0", "auxTrigger1", "auxTrigger2", "auxTrigger3", "I2CData"]:
                    if len(value) > 2:
                        message = (
                            f"Non-empty unsupported field '{key}' found in the frame-variant ScanImage metadata "
                            f"associated with the tiff file {tiff_path}. Update the _load_stack_data() with the logic "
                            f"for parsing the data associated with this field."
                        )
                        console.error(message=message, error=NotImplementedError)
                else:
                    message = (
                        f"Unknown field '{key}' found in the frame-variant ScanImage metadata associated with the tiff "
                        f"file {tiff_path}. Update the _load_stack_data() with the logic for parsing the data "
                        f"associated with this field."
                    )
                    console.error(message=message, error=NotImplementedError)

        # Packages arrays into a dictionary with the same key names as the original metadata fields
        metadata_dict = {
            "frameNumbers": frame_nums,
            "acquisitionNumbers": acq_nums,
            "frameNumberAcquisition": frame_num_acq,
            "frameTimestamps_sec": frame_timestamps,
            "acqTriggerTimestamps_sec": acq_trigger_timestamps,
            "nextFileMarkerTimestamps_sec": next_file_timestamps,
            "endOfAcquisition": end_of_acq,
            "endOfAcquisitionMode": end_of_acq_mode,
            "dcOverVoltage": dc_over_voltage,
            "epochTimestamps_us": epoch_timestamps,
        }

        # Computes the starting and ending frame number
        start_frame = first_frame_number  # This is precomputed to be correct, no adjustment needed
        end_frame = first_frame_number + stack_size - 1  # Ending frame number is length - 1 + start

        # Creates the output path for the compressed stack. Uses 6-digit padding for frame numbering
        output_path = output_dir.joinpath(f"mesoscope_{str(start_frame).zfill(6)}_{str(end_frame).zfill(6)}.tiff")

        # Calculates the total number of batches required to fully process the stack
        num_batches = int(np.ceil(stack_size / batch_size))

        # Creates a TiffWriter to iteratively process and append each batch to the output file. Note, if the file
        # already exists, it will be overwritten.
        with tifffile.TiffWriter(output_path, bigtiff=False) as writer:
            for batch_idx in range(num_batches):
                # Calculates start and end indices for this batch
                start_idx = batch_idx * batch_size
                end_idx = min((batch_idx + 1) * batch_size, stack_size)

                # Reads a batch of original frames
                original_batch = np.array([stack.pages[i].asarray() for i in range(start_idx, end_idx)])

                # Writes the entire batch to the output file using LERC compression
                writer.write(
                    original_batch,
                    compression="lerc",
                    compressionargs={"level": 0.0},  # Lossless compression
                    predictor=True,
                )

                # Verifies the integrity of this batch if requested
                if verify_integrity:
                    # Opens up the compressed file written above for reading
                    with tifffile.TiffFile(output_path) as compressed_stack:
                        # Reads the frames for the current batch using the same indices as used for writing
                        compressed_batch = np.array(
                            [compressed_stack.pages[i].asarray() for i in range(start_idx, end_idx)]
                        )

                        # Compares with original batch
                        if not np.array_equal(compressed_batch, original_batch):
                            message = (
                                f"Compressed batch {batch_idx + 1}/{num_batches} in {output_path} does not match the "
                                f"original in {tiff_path}."
                            )
                            console.error(message=message, error=RuntimeError)

    # Returns extracted metadata dictionary to caller
    return metadata_dict


def _generate_ops(
    metadata: dict[str, Any],
    frame_data: NDArray[np.int16],
    ops_path: Path,
) -> None:
    """Uses frame-invariant ScanImage metadata and static default values to create an ops.json file in the directory
    specified by data_path.

    This function is an implementation of the mesoscope data extraction helper from the suite2p library. The helper
    function has been reworked to use the metadata parsed by tifffile and reimplemented in Python. Primarily, this
    function generates the 'fs', 'dx', 'dy', 'lines', 'nroi', 'nplanes' and 'mesoscan' fields of the 'ops' configuration
    file.

    Notes:
        The generated ops.json file will be saved at the location and filename specified by the ops_path.

    Args:
        metadata: The dictionary containing ScanImage metadata extracted from a mesoscope tiff stack file.
        frame_data: A numpy array containing the extracted pixel data for the first frame of the stack.
        ops_path: The path to the output ops.json file. This is generated by the ProjectData class and passed down to
            this method via the main directory processing function.
    """
    # Extracts the mesoscope framerate from metadata. Uses a fallback value of 4 HZ
    try:
        framerate = float(metadata["FrameData"]["SI.hRoiManager.scanVolumeRate"])  # formerly fs
    except KeyError:
        framerate = float(4)

    # The original extractor code looked for 'SI.hFastZ.userZs' tag, but the test images do not have this tag at all.
    # It is likely that ScanImage changed the tags at some point, and that 'numFastZActuators' tag is the new
    # equivalent.
    nplanes = int(metadata["FrameData"]["SI.hStackManager.numFastZActuators"])

    # Extracts the data about all ROIs
    si_rois: list[dict[str, Any]] = metadata["RoiGroups"]["imagingRoiGroup"]["rois"]

    # Extracts the ROI dimensions for each ROI. Original code says 'for each z-plane; but nplanes is not used anywhere
    # in these computations:

    # Preallocates output arrays
    nrois = len(si_rois)
    roi_heights = np.zeros(nrois)
    roi_widths = np.zeros(nrois)
    roi_centers = np.zeros((nrois, 2))
    roi_sizes = np.zeros((nrois, 2))

    # Loops over all ROIs and extracts dimensional information for each ROI from the metadata.
    for i in range(nrois):
        roi_heights[i] = si_rois[i]["scanfields"]["pixelResolutionXY"][1]
        roi_widths[i] = si_rois[i]["scanfields"]["pixelResolutionXY"][0]
        roi_centers[i] = si_rois[i]["scanfields"]["centerXY"][::-1]  # Reverse order to match the original matlab code
        roi_sizes[i] = si_rois[i]["scanfields"]["sizeXY"][::-1]

    # Transforms ROI coordinates into pixel-units, while maintaining accurate relative positions for each ROI.
    roi_centers -= roi_sizes / 2  # Shifts ROI coordinates to mark the top left corner
    roi_centers -= np.min(roi_centers, axis=0)  # Normalizes ROI coordinates to leftmost/topmost ROI
    # Calculates pixels-per-unit scaling factor from ROI dimensions
    scale_factor = np.median(np.column_stack([roi_heights, roi_widths]) / roi_sizes, axis=0)
    min_positions = roi_centers * scale_factor  # Converts ROI positions to pixel coordinates
    min_positions = np.ceil(min_positions)  # This was added to match Spruston lab extraction code

    # Calculates the total number of rows across all ROIs (rows of pixels acquired while imaging ROIs)
    total_rows = np.sum(roi_heights)

    # Calculates the number of flyback pixels between ROIs. These are the pixels acquired when the galvos are moving
    # between frames.
    n_flyback = (frame_data.shape[0] - total_rows) / max(1, (nrois - 1))

    # Creates an array that stores the start and end row indices for each ROI
    roi_rows = np.zeros((2, nrois))
    # noinspection PyTypeChecker
    temp = np.concatenate([[0], np.cumsum(roi_heights + n_flyback)])
    roi_rows[0] = temp[:-1]  # Starts are all elements except the last
    roi_rows[1] = roi_rows[0] + roi_heights  # Ends calculation stays the same

    # Generates the data to be stored as the JSON config based on the result of the computations above.
    # Note, most of these values were filled based on the 'prototype' ops.json from Tyche F3. For our pipeline they are
    # not really relevant, as we have a separate class that deals with suite2p configuration.
    data = {
        "fs": framerate,
        "nplanes": nplanes,
        "nrois": roi_rows.shape[1],
        "mesoscan": 0 if roi_rows.shape[1] == 1 else 1,
        "diameter": [6, 9],
        "max_iterations": 50,
        "num_workers_roi": -1,
        "keep_movie_raw": 0,
        "delete_bin": 1,
        "batch_size": 1000,
        "nimg_init": 400,
        "tau": 1.25,
        "combined": 0,
        "nonrigid": 1,
        "preclassify": 0.5,
        "do_registration": 1,
        "roidetect": 1,
        "multiplane_parallel": 1,
    }

    # When the config is generated for a mesoscope scan, stores ROI offsets (dx, dy) and line indices (lines) for
    # each ROI
    if data["mesoscan"]:
        # noinspection PyTypeChecker
        data["dx"] = [round(min_positions[i, 1]) for i in range(nrois)]
        # noinspection PyTypeChecker
        data["dy"] = [round(min_positions[i, 0]) for i in range(nrois)]
        data["lines"] = [list(range(int(roi_rows[0, i]), int(roi_rows[1, i]))) for i in range(nrois)]

    # Saves the generated config as JSON file (ops.json)
    with open(ops_path, "w") as f:
        # noinspection PyTypeChecker
        json.dump(data, f, separators=(",", ":"), indent=None)  # Maximizes data compression


def _process_invariant_metadata(file: Path, ops_path: Path, metadata_path: Path) -> None:
    """Extracts frame-invariant ScanImage metadata from the target tiff file and uses it to generate metadata.json and
    ops.json files.

    This function only needs to be called for one raw ScanImage TIFF stack acquired as part of the same experimental
    session. It extracts the ScanImage metadata that is common for all frames across all stacks and outputs it as a
    metadata.json file. This function also calls the _generate_ops() function that generates a suite2p ops.json file
    from the parsed metadata.

    Notes:
        This function is primarily designed to preserve the metadata before compressing raw TIFF stacks with the
        Limited Error Raster Compression (LERC) scheme.

    Args:
        file: The path to the mesoscope TIFF stack file. This can be any file in the directory as the
            frame-invariant metadata is the same for all stacks.
        ops_path: The path to the ops.json file that should be created by this function. This is resolved by the
            ProjectData class to match the processed project, animal, and session combination.
        metadata_path: The path to the metadata.json file that should be created by this function. This is resolved
            by the ProjectData class to match the processed project, animal, and session combination.
    """

    # Reads the frame-invariant metadata from the first page (frame) of the stack. This metadata is the same across
    # all frames and stacks.
    with tifffile.TiffFile(file) as tiff:
        metadata = tiff.scanimage_metadata
        frame_data = tiff.asarray(key=0)  # Loads the data for the first frame in the stack to generate ops.json

    # Writes the metadata as a JSON file.
    with open(metadata_path, "w") as json_file:
        # noinspection PyTypeChecker
        json.dump(metadata, json_file, separators=(",", ":"), indent=None)  # Maximizes data compression

    # Also uses extracted metadata to generate the ops.json configuration file for scanImage processing.
    _generate_ops(
        metadata=metadata,  # type: ignore
        frame_data=frame_data,
        ops_path=ops_path,
    )


def _preprocess_video_names(session_data: SessionData) -> None:
    """Renames the video files generated during runtime to use human-friendly camera names, rather than ID-codes.

    This is a minor preprocessing function primarily designed to make further data processing steps more human-readable.

    Notes:
        This function assumes that the runtime uses 3 cameras with IDs 51 (face camera), 62 (left camera), and 73
        (right camera).

    Args:
        session_data: The SessionData instance that manages the data for the processed session.
    """

    # Resolves the path to the camera frame directory
    camera_frame_directory = session_data.camera_frames_path

    # Renames the video files to use human-friendly names. Assumes the standard data acquisition configuration with 3
    # cameras and predefined camera IDs.
    if camera_frame_directory.joinpath("051.mp4").exists():
        os.renames(
            old=camera_frame_directory.joinpath("051.mp4"),
            new=camera_frame_directory.joinpath("face_camera.mp4"),
        )
    if camera_frame_directory.joinpath("062.mp4").exists():
        os.renames(
            old=camera_frame_directory.joinpath("062.mp4"),
            new=camera_frame_directory.joinpath("left_camera.mp4"),
        )
    if camera_frame_directory.joinpath("073.mp4").exists():
        os.renames(
            old=camera_frame_directory.joinpath("073.mp4"),
            new=camera_frame_directory.joinpath("right_camera.mp4"),
        )


def _pull_mesoscope_data(
    session_data: SessionData,
    num_threads: int = 30,
    remove_sources: bool = True,
    verify_transfer_integrity: bool = True,
) -> None:
    """Pulls the frames acquired by the mesoscope from the ScanImagePC to the VRPC.

    This function should be called after the data acquisition runtime to aggregate all recorded data on the VRPC
    before running the preprocessing pipeline. The function expects that the mesoscope frames source directory
    contains only the frames acquired during the current session runtime, the MotionEstimator.me and
    zstack.mat used for motion registration.

    Notes:
        It is safe to call this function for sessions that did not acquire mesoscope frames. It is designed to
        abort early if it cannot discover the cached mesoscope frames data for the target session on the ScanImagePC.

        This function expects that the data acquisition runtime has renamed the mesoscope_frames source directory for
        the session to include the session name. Manual intervention may be necessary if the runtime fails before the
        mesoscope_frames source directory is renamed.

        This function is configured to parallelize data transfer and verification to optimize runtime speeds where
        possible.

        When the function is called for the first time for a particular project and animal combination, it also
        'persists' the MotionEstimator.me file before moving all mesoscope data to the VRPC. This creates the
        reference for all further motion estimation procedures carried out during future sessions.

    Args:
        session_data: The SessionData instance that manages the data for the processed session.
        remove_sources: Determines whether to remove the transferred mesoscope frame data from the ScanImagePC.
            Generally, it is recommended to remove source data to keep ScanImagePC disk usage low. Note, setting
            this to True will only mark the data for removal. The data will not be removed until 'purge-data' command
            is used from the terminal.
        verify_transfer_integrity: Determines whether to verify the integrity of the transferred data. This is
            performed before source folder is marked for removal from the ScanImagePC if remove_sources is True.
    """
    # Uses the session name to determine the path to the folder that stores raw mesoscope data on the ScanImage PC.
    session_name = session_data.session_name
    source = session_data.mesoscope_root_path.joinpath(f"{session_name}_mesoscope_frames")

    # If the source folder does not exist or is already marked for deletion by the ubiquitin marker, the mesoscope data
    # has already been pulled to the VRPC and there is no need to pull the frames again. In this case, returns early
    if not source.exists() or source.joinpath("ubiquitin.bin").exists():
        return

    # Otherwise, if the source exists and is not marked for deletion, pulls the frame to the target directory:

    # Precreates the temporary storage directory for the pulled data.
    destination = session_data.raw_data_path.joinpath("raw_mesoscope_frames")
    ensure_directory_exists(destination)

    # Defines the set of extensions to look for when verifying source folder contents
    extensions = {"*.me", "*.mat", "*.tiff", "*.tif"}

    # Verifies that all required files are present on the ScanImage PC. This loop will run until the user ensures
    # all files are present or fails five times in a row.
    for attempt in range(5):  # A maximum of 5 reattempts is allowed
        # Extracts the names of files stored in the source folder
        files: tuple[Path, ...] = tuple([path for ext in extensions for path in source.glob(ext)])
        file_names: tuple[str, ...] = tuple([file.name for file in files])
        error = False

        # Ensures the folder contains motion estimator data files
        if "MotionEstimator.me" not in file_names:
            message = (
                f"Unable to pull the mesoscope-acquired data from the ScanImage PC to the VRPC. The "
                f"'mesoscope_frames' ScanImage PC directory for the session {session_name} does not contain the "
                f"MotionEstimator.me file, which is required for further frame data processing."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            error = True

        if "zstack.mat" not in file_names:
            message = (
                f"Unable to pull the mesoscope-acquired data from the ScanImage PC to the VRPC. The "
                f"'mesoscope_frames' ScanImage PC directory for the session {session_name} does not contain the "
                f"zstack.mat file, which is required for further frame data processing."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            error = True

        # Prevents pulling an empty folder. At a minimum, we expect 2 motion estimation files and one TIFF stack
        # file
        if len(files) < 3:
            message = (
                f"Unable to pull the mesoscope-acquired data from the ScanImage PC to the VRPC. The "
                f"'mesoscope_frames' ScanImage PC for the session {session_name} does not contain the minimum expected "
                f"number of files (3). This indicates that no frames were acquired during runtime or that the frames "
                f"were saved at a different location."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            error = True

        # Breaks the loop if all files are present
        if not error:
            break

        # Otherwise, waits for the user to move the files into the requested directory and continues the runtime
        message = (
            f"Unable to locate all required Mesoscope data files when pulling the session {session_name} data to the "
            f"VRPC. Move all requested files to the mesoscope_frames directory on the ScanImage PC before "
            f"continuing the runtime. Note, cycling through this message 5 times in a row will abort the "
            f"preprocessing with a RuntimeError."
        )
        console.echo(message=message, level=LogLevel.WARNING)
        input("Enter anything to continue: ")

        # If the user has repeatedly failed 10 attempts in a row, exits with a runtime error
        if attempt >= 4:
            message = (
                f"Failed 5 consecutive attempts to locate all required mesoscope frame files. Aborting mesoscope "
                f"data processing and terminating the preprocessing runtime."
            )
            console.error(message=message, error=RuntimeError)

    # If the processed project and animal combination does not have a reference MotionEstimator.me saved in the
    # persistent ScanImagePC directory, copies the MotionEstimator.me to the persistent directory. This ensures that
    # the first ever created MotionEstimator.me is saved as the reference MotionEstimator.me for further sessions.
    persistent_motion_estimator_path = session_data.mesoscope_persistent_path.joinpath("MotionEstimator.me")
    ensure_directory_exists(persistent_motion_estimator_path.parent)
    if not persistent_motion_estimator_path.exists():
        sh.copy2(src=source.joinpath("MotionEstimator.me"), dst=persistent_motion_estimator_path)

    # Generates the checksum for the source folder if transfer integrity verification is enabled.
    if verify_transfer_integrity:
        calculate_directory_checksum(directory=source, num_processes=None, save_checksum=True)

    # Transfers the mesoscope frames data from the ScanImage PC to the local machine.
    transfer_directory(
        source=source, destination=destination, num_threads=num_threads, verify_integrity=verify_transfer_integrity
    )

    # Removes the checksum file after the transfer is complete. The checksum will be recalculated for the whole
    # session directory during preprocessing, so there is no point in keeping the original mesoscope checksum file.
    if verify_transfer_integrity:
        destination.joinpath("ax_checksum.txt").unlink(missing_ok=True)

    # After the transfer completes successfully (including integrity verification), tags (marks) the source
    # directory for removal. Specifically, deposits an 'ubiquitin.bin' marker, which is used by our data purging
    # runtime to discover and remove directories that are no longer necessary.
    if remove_sources:
        marker_path = source.joinpath("ubiquitin.bin")
        marker_path.touch()


def _preprocess_mesoscope_directory(
    session_data: SessionData,
    num_processes: int,
    remove_sources: bool = True,
    batch: bool = False,
    verify_integrity: bool = False,
    batch_size: int = 250,
) -> None:
    """Loops over all multi-frame Mesoscope TIFF stacks in the mesoscope_frames, recompresses them using Limited Error
    Raster Compression (LERC) scheme, and extracts ScanImage metadata.

    This function is used as a preprocessing step for mesoscope-acquired data that optimizes the size of raw images for
    long-term storage and streaming over the network. To do so, all stacks are re-encoded using LERC scheme, which
    achieves ~70% compression ratio, compared to the original frame stacks obtained from the mesoscope. Additionally,
    this function also extracts frame-variant and frame-invariant ScanImage metadata from raw stacks and saves it as
    efficiently encoded JSON (.json) and compressed numpy archive (.npz) files to minimize disk space usage.

    Notes:
        This function is specifically calibrated to work with TIFF stacks produced by the ScanImage matlab software.
        Critically, these stacks are named using '_' to separate acquisition and stack number from the rest of the
        file name, and the stack number is always found last, e.g.: 'Tyche-A7_2022_01_25_1__00001_00067.tif'. If the
        input TIFF files do not follow this naming convention, the function will not process them. Similarly, if the
        stacks do not contain ScanImage metadata, they will be excluded from processing.

        To optimize runtime efficiency, this function employs multiple processes to work with multiple TIFFs at the
        same time. Given the overall size of each image dataset, this function can run out of RAM if it is allowed to
        operate on the entire folder at the same time. To prevent this, disable verification, use fewer processes, or
        change the batch_size to load fewer frames in memory at the same time.

        In addition to frame compression and data extraction, this function also generates the ops.json configuration
        file. This file is used during suite2p cell registration, performed as part of our standard data processing
        pipeline.

    Args:
        session_data: The SessionData instance that manages the data for the processed session.
        num_processes: The maximum number of processes to use while processing the directory. Each process is used to
            compress a stack of TIFF files in parallel.
        remove_sources: Determines whether to remove the original TIFF files after they have been processed.
        batch: Determines whether the function is called as part of batch-processing multiple directories. This is used
            to optimize progress reporting to avoid cluttering the terminal window.
        verify_integrity: Determines whether to verify the integrity of compressed data against the source data.
            The conversion does not alter the source data, so it is usually safe to disable this option, as the chance
            of compromising the data is negligible. Note, enabling this function doubles the RAM used by each parallel
            worker spawned by this function.
        batch_size: Determines how many frames are loaded into memory at the same time during processing. Note, the same
            number of frames will be loaded from each stack processed in parallel.
    """
    # Resolves the paths to the specific directories used during processing
    image_directory = session_data.raw_data_path.joinpath("raw_mesoscope_frames")

    # If raw_mesoscope_frames directory does not exist, either the mesoscope frames are already processed or were not
    # acquired at all. Aborts processing early.
    if not image_directory.exists():
        return

    # Otherwise, resolves the paths to the output directories and files
    output_directory = session_data.raw_data_path.joinpath("mesoscope_frames")
    ensure_directory_exists(output_directory)  # Generates the directory
    frame_invariant_metadata_path = output_directory.joinpath("frame_invariant_metadata.json")
    frame_variant_metadata_path = output_directory.joinpath("frame_variant_metadata.npz")
    ops_path = output_directory.joinpath("ops.json")

    # Precreates the dictionary to store frame-variant metadata extracted from all TIFF frames before they are
    # compressed into BigTiff.
    all_metadata = defaultdict(list)

    # Finds all TIFF files in the input directory (non-recursive).
    tiff_files = list(image_directory.glob("*.tif")) + list(image_directory.glob("*.tiff"))

    # Sorts files with a valid naming pattern and filters out (removes) files that are not ScanImage TIFF stacks.
    tiff_files = [f for f in tiff_files if _get_stack_number(f) is not None]
    tiff_files.sort(key=_get_stack_number)  # type: ignore

    # Goes over each stack and, for each, determines the position of the first frame from the stack in the overall
    # sequence of frames acquired by all stacks. This is used to map frames stored in multiple stacks to a single
    # session-wide sequence.
    frame_numbers = []
    starting_frame = 1
    for file in tiff_files:
        stack_size = _check_stack_size(file)
        if stack_size > 0:
            # Appends the starting frame number to the list and increments the stack list
            frame_numbers.append(starting_frame)
            starting_frame += stack_size
        else:
            # Stack size of 0 suggests that the checked file is not a ScanImage TIFF stack, so it is removed from
            # processing
            tiff_files.remove(file)

    # Converts to tuple for efficiency
    tiff_files = tuple(tiff_files)  # type: ignore
    frame_numbers = tuple(frame_numbers)  # type: ignore

    # Ends the runtime early if there are no valid TIFF files to process after filtering
    if len(tiff_files) == 0:
        return

    # Extracts frame invariant metadata using the first frame of the first TIFF stack. Since this metadata is the
    # same for all stacks, it is safe to use any available stack. We use the first one for consistency with
    # suite2p helper scripts.
    _process_invariant_metadata(file=tiff_files[0], ops_path=ops_path, metadata_path=frame_invariant_metadata_path)

    # Uses partial to bind the constant arguments to the processing function
    process_func = partial(
        _process_stack,
        output_dir=output_directory,
        verify_integrity=verify_integrity,
        batch_size=batch_size,
    )

    # Processes each tiff stack in parallel
    with ProcessPoolExecutor(max_workers=num_processes) as executor:
        # Submits all tasks
        future_to_file = set()
        for file, frame in zip(tiff_files, frame_numbers):
            future_to_file.add(executor.submit(process_func, file, frame))

        if not batch:
            # Shows progress with tqdm when not in batch mode
            with tqdm(
                total=len(tiff_files),
                desc=f"Processing TIFF stacks for {Path(*image_directory.parts[-6:])}",
                unit="stack",
            ) as pbar:
                for future in as_completed(future_to_file):
                    for key, value in future.result().items():
                        all_metadata[key].append(value)
                    pbar.update(1)
        else:
            # For batch mode, processes without progress tracking
            for future in as_completed(future_to_file):
                for key, value in future.result().items():
                    all_metadata[key].append(value)

    # Saves concatenated metadata as compressed numpy archive
    metadata_dict = {key: np.concatenate(value) for key, value in all_metadata.items()}
    np.savez_compressed(frame_variant_metadata_path, **metadata_dict)

    # Moves motion estimator files to the mesoscope_frames directory. This way, ALL mesoscope-related data is stored
    # under mesoscope_frames.
    sh.move(
        src=image_directory.joinpath("MotionEstimator.me"),
        dst=output_directory.joinpath("MotionEstimator.me"),
    )
    sh.move(
        src=image_directory.joinpath("zstack.mat"),
        dst=output_directory.joinpath("zstack.mat"),
    )

    # If configured, the processing function ensures that
    if remove_sources:
        _delete_directory(image_directory)


def _preprocess_log_directory(
    session_data: SessionData, num_processes: int, remove_sources: bool = True, verify_integrity: bool = False
) -> None:
    """Compresses all .npy (uncompressed) log entries stored in the behavior log directory into one or more .npz
    archives.

    This service function is used during data preprocessing to optimize the size and format used to store all log
    entries. Primarily, this is necessary to facilitate data transfer over the network and log processing on the
    BioHPC server.

    Args:
        session_data: The SessionData instance that manages the data for the processed session.
        num_processes: The maximum number of processes to use while processing the directory.
        remove_sources: Determines whether to remove the original .npy files after they are compressed into .npz
            archives. It is recommended to have this option enabled.
        verify_integrity: Determines whether to verify the integrity of compressed data against the source data.
            It is advised to have this disabled for most runtimes, as data corruption is highly unlikely, but enabling
            this option adds a significant overhead to the processing time.

    Raises:
        RuntimeError: If the target log directory contains both compressed and uncompressed log entries.
    """
    # Resolves the path to the log directory, using either the input or initialized logger class.
    log_directory = session_data.raw_data_path.joinpath("behavior_data_log")

    # Searches for compressed and uncompressed files inside the log directory
    compressed_files: list[Path] = [file for file in log_directory.glob("*.npz")]
    uncompressed_files: list[Path] = [file for file in log_directory.glob("*.npy")]

    # If there are no uncompressed files, ends the runtime early
    if len(uncompressed_files) < 0:
        return

    # If the input directory contains .npy (uncompressed) log entries and no compressed log entries, compresses all log
    # entries in the directory
    if len(compressed_files) == 0 and len(uncompressed_files) > 0:
        compress_npy_logs(
            log_directory=log_directory,
            remove_sources=remove_sources,
            memory_mapping=False,
            verbose=True,
            compress=True,
            verify_integrity=verify_integrity,
            max_workers=num_processes,
        )

    # If both compressed and uncompressed log files existing in the same directory, aborts with an error
    elif len(compressed_files) > 0 and len(uncompressed_files) > 0:
        message = (
            f"The log directory for session {session_data.session_name} contains both compressed and uncompressed log "
            f"files. Since compression overwrites the .npz archive with the processed data, it is unsafe to proceed "
            f"with log compression in automated mode. Manually back up the existing .npz files, remove them from the "
            f"log directory and call the processing method again."
        )
        console.error(message, error=RuntimeError)


def _push_data(
    session_data: SessionData,
    parallel: bool = True,
    num_threads: int = 15,
) -> None:
    """Copies the raw_data directory from the VRPC to the NAS and the BioHPC server.

    This internal method is called as part of preprocessing to move the preprocessed data to the NAS and the server.
    This method generates the xxHash3-128 checksum for the source folder that the server processing pipeline uses to
    verify the integrity of the transferred data.

    Notes:
        The method also replaces the persisted zaber_positions.yaml file with the file generated during the managed
        session runtime. This ensures that the persisted file is always up to date with the current zaber motor
        positions.

    Args:
        session_data: The SessionData instance that manages the data for the processed session.
        parallel: Determines whether to parallelize the data transfer. When enabled, the method will transfer the
            data to all destinations at the same time (in-parallel). Note, this argument does not affect the number
            of parallel threads used by each transfer process or the number of threads used to compute the
            xxHash3-128 checksum. This is determined by the 'num_threads' argument (see below).
        num_threads: Determines the number of threads used by each transfer process to copy the files and calculate
            the xxHash3-128 checksums. Since each process uses the same number of threads, it is highly
            advised to set this value so that num_threads * 2 (number of destinations) does not exceed the total
            number of CPU cores - 4.
    """

    # Resolves source and destination paths
    session_name = session_data.session_name
    animal_name = session_data.animal_id
    project_name = session_data.project_name

    # Resolves a tuple of destination paths
    destinations = (
        session_data.nas_root_path.joinpath(project_name, animal_name, session_name, "raw_data"),
        session_data.server_root_path.joinpath(project_name, animal_name, session_name, "raw_data"),
    )

    # Computes the xxHash3-128 checksum for the source folder
    calculate_directory_checksum(directory=session_data.raw_data_path, num_processes=None, save_checksum=True)

    # If the method is configured to transfer files in parallel, submits tasks to a ProcessPoolExecutor
    if parallel:
        with ProcessPoolExecutor(max_workers=len(destinations)) as executor:
            futures = {
                executor.submit(
                    transfer_directory,
                    source=session_data.raw_data_path,
                    destination=destination,
                    num_threads=num_threads,
                    verify_integrity=False,  # This is now done on the server directly
                ): destination
                for destination in destinations
            }
            for future in as_completed(futures):
                # Propagates any exceptions from the transfers
                future.result()

    # Otherwise, runs the transfers sequentially. Note, transferring individual files is still done in parallel, but
    # the transfer is performed for each destination sequentially.
    else:
        for destination in destinations:
            transfer_directory(
                source=session_data.raw_data_path,
                destination=destination,
                num_threads=num_threads,
                verify_integrity=False,  # This is now done on the server directly
            )


def _preprocess_google_sheet_data(session_data: SessionData) -> None:
    """Updates the water restriction log and the surgery_data.yaml file.

    This internal method is called as part of preprocessing. Primarily, it is used to ensure that the surgery data
    extracted and stored in the 'metadata' folder of each processed animal is actual. It also updates the water
    restriction log for the managed animal to reflect the water received before and after runtime. This step improves
    user experience by ensuring all relevant data is always kept together on the NAS and BioHPC server while preventing
    the experimenter from manually updating the log after data preprocessing.

    Raises:
        ValueError: If the session_type attribute of the input SessionData instance is not one of the supported options.
    """

    # Resolves the animal ID (name)
    animal_id = int(session_data.animal_id)

    message = f"Writing water restriction log entry..."
    console.echo(message=message, level=LogLevel.INFO)

    # Loads the session descriptor file to read the data needed to update the wr log
    descriptor_path = session_data.session_descriptor_path
    descriptor: RunTrainingDescriptor | LickTrainingDescriptor | MesoscopeExperimentDescriptor
    if session_data.session_type == "lick_training":
        descriptor = LickTrainingDescriptor.from_yaml(descriptor_path)  # type: ignore
    elif session_data.session_type == "run_training":
        descriptor = RunTrainingDescriptor.from_yaml(descriptor_path)  # type: ignore
    elif session_data.session_type == "experiment":
        descriptor = MesoscopeExperimentDescriptor.from_yaml(descriptor_path)  # type: ignore
    else:
        message = (
            f"Unable to extract the water restriction data from the session descriptor file for session "
            f"{session_data.session_name}. Expected the session_type field of the SessionData instance to be one of "
            f"the supported options (lick_training, run_training, experiment) but instead encountered "
            f"{session_data.session_type}."
        )
        console.error(message, error=ValueError)

        # This should not be reachable, it is here to appease mypy.
        raise ValueError(message)  # pragma: no cover

    # Calculates the total volume of water, in ml, the animal received during and after the session
    training_water = round(descriptor.dispensed_water_volume_ml, ndigits=3)
    experimenter_water = round(descriptor.experimenter_given_water_volume_ml, ndigits=3)
    total_water = training_water + experimenter_water

    # Connects to the WR sheet and generates the new water restriction log entry
    wr_sheet = WaterSheetData(
        animal_id=animal_id,
        credentials_path=Path(session_data.credentials_path),
        sheet_id=session_data.water_log_sheet_id,
    )

    wr_sheet.update_water_log(
        mouse_weight=descriptor.mouse_weight_g,
        water_ml=total_water,
        experimenter_id=descriptor.experimenter,
    )

    message = f"Water restriction log entry: written."
    console.echo(message=message, level=LogLevel.SUCCESS)

    message = f"Updating animal surgery data file..."
    console.echo(message=message, level=LogLevel.INFO)

    # Resolves the paths to the surgery data files stored inside the metadata folder of the managed animal at each
    # destination.
    local_surgery_path = session_data.local_metadata_path.joinpath("surgery_metadata.yaml")
    server_surgery_path = session_data.server_metadata_path.joinpath("surgery_metadata.yaml")
    nas_surgery_path = session_data.nas_metadata_path.joinpath("surgery_metadata.yaml")

    # Loads and parses the data from the surgery log Google Sheet file
    sl_sheet = SurgerySheet(
        project_name=session_data.project_name,
        credentials_path=Path(session_data.credentials_path),
        sheet_id=session_data.surgery_sheet_id,
    )
    data: SurgeryData = sl_sheet.extract_animal_data(animal_id=animal_id)

    # Saves the data as a .yaml file locally, to the server, and the NAS.
    data.to_yaml(local_surgery_path)
    data.to_yaml(server_surgery_path)
    data.to_yaml(nas_surgery_path)

    message = f"Surgery data: saved."
    console.echo(message=message, level=LogLevel.SUCCESS)


def _resolve_telomere_markers(server_root_path: Path, local_root_path: Path) -> None:
    """Checks the data stored on Sun lab BioHPC server for the presence of telomere.bin markers and removes all matching
    directories on the VRPC.

    Specifically, this function iterates through all raw_data directories on the VRPC, checks if the corresponding
    directory on the BioHPC server contains a telomere.bin marker, and removes the local raw_data directory if a marker
    is found.

    Args:
        server_root_path: The path to the root directory used to store all experiment and training data on the Sun lab
            BioHPC server.
        local_root_path: The path to the root directory used to store all experiment and training data on the VRPC.
    """
    # Finds all raw_data directories in the local path for which there is a raw_data with the telomere.bin marker on
    # the server
    deletion_candidates = []
    for raw_data_path in local_root_path.rglob("raw_data"):
        # Constructs the relative path to the raw_data directory from the local root
        relative_path = raw_data_path.relative_to(local_root_path)

        # Constructs the corresponding server path
        server_path = server_root_path.joinpath(relative_path)

        # Checks if the telomere.bin marker exists in the server path
        if server_path.joinpath("telomere.bin").exists():
            # If marker exists, removes the local (VRPC) raw_data directory
            deletion_candidates.append(raw_data_path)

    # Iteratively removes all deletion candidates gathered above
    for candidate in tqdm(deletion_candidates, desc="Deleting redundant VRPC directories", unit="directory"):
        _delete_directory(directory_path=candidate)


def _resolve_ubiquitin_markers(mesoscope_root_path: Path) -> None:
    """Checks the data stored on the ScanImage PC for the presence of ubiquitin.bin markers and removes all directories
    that contain the marker.

    This function is used to clear out cached mesoscope frame directories on the ScanImage PC once they have been safely
    copied and processed on the VRPC.

    Args:
        mesoscope_root_path: The path to the root directory used to store all mesoscope-acquired data on the ScanImage
            (Mesoscope) PC.
    """
    # Builds a list of deletion candidates and then iteratively removes all discovered directories marked for
    # deletion
    file: Path
    deletion_candidates = [file.parent for file in mesoscope_root_path.rglob("ubiquitin.bin")]
    for candidate in tqdm(deletion_candidates, desc="Deleting redundant ScanImagePC directories", unit="directory"):
        _delete_directory(directory_path=candidate)


def purge_redundant_data(
    remove_ubiquitin: bool,
    remove_telomere: bool,
    local_root_path: Path = Path("/media/Data/Experiments"),
    server_root_path: Path = Path("/media/cbsuwsun/storage/sun_data"),
    mesoscope_root_path: Path = Path("/home/cybermouse/scanimage/mesodata"),
) -> None:
    """Loops over ScanImagePC and VRPC directories that store training and experiment data and removes no longer
    necessary data caches.

    This function searches the ScanImagePC and VRPC for no longer necessary directories and removes them from the
    respective systems. ScanImagePC directories are marked for deletion once they are safely copied to the VRPC (and the
    integrity of the copied data is verified using xxHash-128 checksum). VRPC directories are marked for deletion once
    the data is safely copied to the BioHPC server and the server verifies the integrity of the copied data using
    xxHash-128 checksum.

    Notes:
        This is a service function intended to maintain the ScanImagePC and VRPC disk space. To ensure data integrity
        and redundancy at all processing stages, we do not remove the raw data from these PCs even if it has been
        preprocessed and moved to long-term storage destinations. However, once the data is moved to the BioHPC server
        and the NAS, it is generally safe to remove the copies stored on the ScanImagePC and VRPC.

        While the NAS is currently not verified for transferred data integrity, it is highly unlikely that the transfer
        process leads to data corruption. Overall, the way this process is structured ensures that at all stages of
        data processing there are at least two copies of the data stored on two different machines.

        Currently, this function does not discriminate between projects or animals. It will remove all data marked for
        deletion via the ubiquitin.bin marker or the telomere.bin marker.

    Args:
        remove_ubiquitin: Determines whether to remove ScanImagePC mesoscope_frames directories marked for deletion
            with ubiquitin.bin markers. Specifically, this allows removing directories that have been safely moved to
            the VRPC.
        remove_telomere: Determines whether to remove VRPC directories whose corresponding BioHPC-server directories
            are marked with telomere.bin markers. Specifically, this allows removing directories that have been safely
            moved to and processed by the BioHPC server.
        local_root_path: The path to the root directory of the VRPC used to store all experiment and training data.
        server_root_path: The path to the root directory of the BioHPC server used to store all experiment and
            training data.
        mesoscope_root_path: The path to the root directory of the ScanImagePC used to store all
            mesoscope-acquired frame data.
    """

    # Enables console, if it is not enabled
    if not console.enabled:
        console.enable()

    message = "Initializing data purging..."
    console.echo(message=message, level=LogLevel.INFO)

    # Removes no longer necessary ScanImagePC directories (cached mesoscope frames)
    if remove_ubiquitin:
        message = "Purging redundant ScanImagePC directories..."
        console.echo(message=message, level=LogLevel.INFO)
        _resolve_ubiquitin_markers(mesoscope_root_path)

    # Removes no longer necessary VRPC directories (raw_data folders)
    if remove_telomere:
        message = "Purging redundant VRPC directories..."
        console.echo(message=message, level=LogLevel.INFO)
        _resolve_telomere_markers(server_root_path, local_root_path)

    message = "Purging: Complete"
    console.echo(message=message, level=LogLevel.SUCCESS)
