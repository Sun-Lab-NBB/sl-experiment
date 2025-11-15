"""This module provides the assets for preprocessing the data acquired by the Mesoscope-VR data acquisition system
during a session's runtime and moving it to the long-term storage destinations.
"""

import os
import json
import shutil as sh
from typing import Any
from pathlib import Path
from datetime import datetime
from functools import partial
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from tqdm import tqdm
import numpy as np
import tifffile
from natsort_rs import natsort as natsorted
from sl_shared_assets import (
    SessionData,
    SurgeryData,
    SessionTypes,
    RunTrainingDescriptor,
    LickTrainingDescriptor,
    WindowCheckingDescriptor,
    MesoscopeExperimentDescriptor,
    transfer_directory,
    calculate_directory_checksum,
    delete_directory,
)
from ataraxis_base_utilities import LogLevel, console, ensure_directory_exists
from ataraxis_data_structures import assemble_log_archives

from .tools import MesoscopeData, get_system_configuration
from ..shared_components import WaterLog, SurgeryLog

_METADATA_SCHEMA = {
    "frameNumbers": (np.int32, int),
    "acquisitionNumbers": (np.int32, int),
    "frameNumberAcquisition": (np.int32, int),
    "frameTimestamps_sec": (np.float64, float),
    "acqTriggerTimestamps_sec": (np.float64, float),
    "nextFileMarkerTimestamps_sec": (np.float64, float),
    "endOfAcquisition": (np.int32, int),
    "endOfAcquisitionMode": (np.int32, int),
    "dcOverVoltage": (np.int32, int),
}
"""Defines the schema for the frame-variant ScanImage metadata expected by the _process_stack() function
when parsing mesoscope-generated metadata. This schema is statically written to match the ScanImage version currently 
used by the Mesoscope-VR system."""

_IGNORED_METADATA_FIELDS = {"auxTrigger0", "auxTrigger1", "auxTrigger2", "auxTrigger3", "I2CData"}
"""Stores the frame-invariant ScanImage metadata fields that are currently not used by the Mesoscope-VR system."""


def _verify_and_get_stack_size(file: Path) -> int:
    """Reads the header of the specified TIFF file, and, if the file is a valid mesoscope frame stack, extracts and
    returns its size in frames.

    Args:
        file: The path to the TIFF file to evaluate.

    Returns:
        If the file is a valid mesoscope frame stack, returns the number of frames (pages) in the stack. Otherwise,
        returns 0 to indicate that the file is not a valid mesoscope stack.
    """
    with tifffile.TiffFile(file) as tiff:
        # Gets the number of pages (frames) from the tiff file's header
        n_frames = len(tiff.pages)

        # Considers all files with more than one page, a 2-dimensional (monochrome) image layout, and ScanImage metadata
        # a candidate stack for further processing. For these stacks, returns the discovered stack size
        # (number of frames).
        if n_frames > 1 and len(tiff.pages[0].shape) == 2 and tiff.scanimage_metadata is not None:
            return n_frames
        # Otherwise, returns 0 to indicate that the file is not a valid mesoscope frame stack.
        return 0


def _process_stack(
    tiff_path: Path, first_frame_number: int, output_directory: Path, batch_size: int = 250
) -> dict[str, Any]:
    """Recompresses the target mesoscope frame stack TIFF file using the Limited Error Raster Coding (LERC) scheme and
    extracts its frame-variant ScanImage metadata.

    Notes:
        This function is designed to be parallelized to work on multiple TIFF files at the same time.

        As part of its runtime, the function strips the extracted metadata from the recompressed frame stack to reduce
        its size.

    Raises:
        NotImplementedError: If the extracted frame-variant ScanImage metadata cannot be processed due to a mismatch
            between the ScanImage version and the version of the sl-experiment library.

    Args:
        tiff_path: The path to the TIFF file that stores the stack of the mesoscope-acquired frames to process.
        first_frame_number: The position (number) of the first frame stored in the stack, relative to the overall
            sequence of frames acquired during the data acquisition session's runtime.
        output_directory: The path to the directory where to save the recompressed stacks.
        batch_size: The number of frames to process at the same time.

    Returns:
        A dictionary containing the extracted frame-variant ScanImage metadata for the processed mesoscope frame stack.
    """
    # Generates the file handle for the current stack
    with tifffile.TiffFile(tiff_path) as stack:
        # Determines the size of the stack
        stack_size = len(stack.pages)

        # Initializes arrays for storing the extracted metadata using the schema
        arrays = {key: np.zeros(stack_size, dtype=dtype)
                  for key, (dtype, _) in _METADATA_SCHEMA.items()}

        # Also initializes the array for storing the converted frame acquisition timestamps.
        arrays["epochTimestamps_us"] = np.zeros(stack_size, dtype=np.uint64)

        # Loops over each page in the stack and extracts the metadata associated with each frame
        for i, page in enumerate(stack.pages):
            metadata = page.tags["ImageDescription"].value

            # The metadata is returned as a 'newline'-delimited string of key=value pairs. This preprocessing header
            # splits the string into separate key=value pairs. Then, each pair is further separated and processed as
            # necessary
            for line in metadata.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # This section is written to raise errors if it encounters an unexpected (unsupported) metadata field.
                if key in _METADATA_SCHEMA:  # Expected data fields
                    # Use the schema to parse and convert the value
                    _, converter = _METADATA_SCHEMA[key]
                    arrays[key][i] = converter(value)
                elif key == "epoch":  # Epoch data is converted to the Sun lab's timestamp format.
                    # Parses the epoch [year month day hour minute second.microsecond] as microseconds elapsed since
                    # the UTC onset.
                    epoch_vals = [float(x) for x in value[1:-1].split()]
                    timestamp = int(
                        datetime(
                            int(epoch_vals[0]),
                            int(epoch_vals[1]),
                            int(epoch_vals[2]),
                            int(epoch_vals[3]),
                            int(epoch_vals[4]),
                            int(epoch_vals[5]),
                            int((epoch_vals[5] % 1) * 1_000_000),
                        ).timestamp()
                        * 1_000_000
                    )  # Converts to microseconds
                    arrays["epochTimestamps_us"][i] = timestamp
                elif key in _IGNORED_METADATA_FIELDS:
                    # These fields are known but not currently used by the system. This section ensures these fields are
                    # empty to prevent accidental data loss.
                    if len(value) > 2:
                        message = (
                            f"Non-empty unsupported field '{key}' found in the frame-variant ScanImage metadata "
                            f"associated with the tiff file {tiff_path}. Update the _process_stack() function with the "
                            f"logic for parsing the data associated with this field."
                        )
                        console.error(message=message, error=NotImplementedError)
                else:
                    # Unknown field - raise error to ensure schema is updated
                    message = (
                        f"Unknown field '{key}' found in the frame-variant ScanImage metadata associated with the tiff "
                        f"file {tiff_path}. Update the _process_stack() function with the logic for parsing the data "
                        f"associated with this field."
                    )
                    console.error(message=message, error=NotImplementedError)

        # Computes the starting and ending frame numbers
        start_frame = first_frame_number
        end_frame = first_frame_number + stack_size - 1  # The ending frame number is length - 1 + start

        # Creates the output path for the compressed stack. Uses configured digit padding for frame numbering
        output_path = output_directory.joinpath(
            f"mesoscope_{str(start_frame).zfill(6)}_{str(end_frame).zfill(6)}.tiff"
        )

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

    # Returns extracted metadata dictionary to caller (all keys from arrays dict)
    return arrays


def _process_invariant_metadata(frame_stack_path: Path, ops_path: Path, metadata_path: Path) -> None:
    """Extracts the frame-invariant ScanImage metadata from the target mesoscope frame stack TIFF file and uses it to
    generate the metadata.json and ops.json files.

    Args:
        frame_stack_path: The path to the TIFF file that stores a stack of the mesoscope-acquired frames.
        ops_path: The path to the ops.json file to be created.
        metadata_path: The path to the metadata.json file to be created.
    """
    # Reads the frame-invariant metadata from the first page (frame) of the stack. This metadata is the same across
    # all frames and stacks.
    with tifffile.TiffFile(frame_stack_path) as tiff:
        metadata = tiff.scanimage_metadata
        frame_data = tiff.asarray(key=0)  # Loads the data for the first frame in the stack to generate ops.json

    # Writes the metadata as a JSON file.
    with open(metadata_path, "w") as json_file:
        # noinspection PyTypeChecker
        json.dump(metadata, json_file, separators=(",", ":"), indent=None)  # Maximizes data compression

    # Extracts the mesoscope frame_rate from metadata.
    frame_rate = float(metadata["FrameData"]["SI.hRoiManager.scanVolumeRate"])
    plane_number = int(metadata["FrameData"]["SI.hStackManager.actualNumSlices"])
    channel_number = int(metadata["FrameData"]["SI.hChannels.channelsActive"])
    si_rois: list[dict[str, Any]] | dict[str, Any] = metadata["RoiGroups"]["imagingRoiGroup"]["rois"]

    # If the acquisition only uses a single ROI, si_rois is a single dictionary. Converts it to a list for the code
    # below to work for this acquisition mode.
    if isinstance(si_rois, dict):
        rois = [si_rois]
    else:
        rois = si_rois

    # Extracts the ROI dimensions for each ROI.
    roi_number = len(rois)
    roi_heights = np.array([roi["scanfields"]["pixelResolutionXY"][1] for roi in rois])
    roi_widths = np.array([roi["scanfields"]["pixelResolutionXY"][0] for roi in rois])
    roi_centers = np.array([roi["scanfields"]["centerXY"][::-1] for roi in rois])
    roi_sizes = np.array([roi["scanfields"]["sizeXY"][::-1] for roi in rois])

    # Transforms ROI coordinates into pixel-units, while maintaining accurate relative positions for each ROI.
    roi_centers -= roi_sizes / 2  # Shifts ROI coordinates to mark the top left corner
    roi_centers -= np.min(roi_centers, axis=0)  # Normalizes ROI coordinates to leftmost/topmost ROI
    # Calculates pixels-per-unit scaling factor from ROI dimensions
    scale_factor = np.median(np.column_stack([roi_heights, roi_widths]) / roi_sizes, axis=0)
    min_positions = np.ceil(roi_centers * scale_factor)  # Converts ROI positions to pixel coordinates

    # Calculates the total number of rows across all ROIs (rows of pixels acquired while imaging ROIs)
    total_rows = np.sum(roi_heights)

    # Calculates the number of flyback pixels between ROIs. These are the pixels acquired when the galvos are moving
    # between frames.
    n_flyback = (frame_data.shape[0] - total_rows) // max(1, (roi_number - 1))  # Uses integer division

    # Creates an array that stores the start and end row indices for each ROI
    roi_rows = np.zeros(shape=(2, roi_number), dtype=np.int32)
    # noinspection PyTypeChecker
    temp = np.concatenate([[0], np.cumsum(roi_heights + n_flyback)])
    roi_rows[0] = temp[:-1]  # Stores the first line index for each ROI
    roi_rows[1] = roi_rows[0] + roi_heights  # Stores the last line index for each ROI

    # Extracts the invariant data necessary for the suite2p processing pipeline to be able to load and work with the
    # stack.
    data: dict[str, int | float | list[Any]] = {
        "frame_rate": frame_rate,
        "plane_number": plane_number,
        "channel_number": channel_number,
        "roi_number": roi_rows.shape[1],
        "roi_x_coordinates": [round(min_positions[i, 1]) for i in range(roi_number)],
        "roi_y_coordinates": [round(min_positions[i, 0]) for i in range(roi_number)],
        "roi_lines": [list(range(int(roi_rows[0, i]), int(roi_rows[1, i]))) for i in range(roi_number)]
    }

    # Saves the generated config as a JSON file (ops.json)
    with open(ops_path, "w") as f:
        # noinspection PyTypeChecker
        json.dump(data, f, separators=(",", ":"), indent=None)  # Maximizes data compression


def _preprocess_video_names(session_data: SessionData) -> None:
    """Renames the .MP4 video files generated during the processed data acquisition session's runtime to use
    human-friendly names instead of the source ID codes.

    Args:
        session_data: The SessionData instance that defines the processed session.
    """
    # Resolves the path to the camera frame directory
    camera_frame_directory = session_data.raw_data.camera_data_path
    session_name = session_data.session_name

    # Renames the video files to use human-friendly names. Assumes the standard data acquisition configuration with 2
    # cameras and predefined camera IDs.
    if camera_frame_directory.joinpath("051.mp4").exists():
        os.renames(
            old=camera_frame_directory.joinpath("051.mp4"),
            new=camera_frame_directory.joinpath(f"{session_name}_face_camera.mp4"),
        )
    if camera_frame_directory.joinpath("062.mp4").exists():
        os.renames(
            old=camera_frame_directory.joinpath("062.mp4"),
            new=camera_frame_directory.joinpath(f"{session_name}_body_camera.mp4"),
        )


def _pull_mesoscope_data(
    session_data: SessionData,
    mesoscope_data: MesoscopeData,
    num_threads: int = 30,
    remove_sources: bool = True,
    verify_transfer_integrity: bool = False,
) -> None:
    """Pulls the data acquired by the Mesoscope from the ScanImagePC to the VRPC.

    This function should be called after the data acquisition runtime to aggregate all recorded data on the VRPC
    before running the preprocessing pipeline. The function expects that the mesoscope frames source directory
    contains only the frames acquired during the current session runtime alongside additional data, such as
    MotionEstimation .csv files.

    Notes:
        It is safe to call this function for sessions that did not acquire mesoscope frames. It is designed to
        abort early if it cannot discover the cached mesoscope frames data for the target session on the ScanImagePC.

        This function expects that the data acquisition runtime has renamed the mesoscope_frames source directory for
        the session to include the session name. Manual intervention may be necessary if the runtime fails before the
        mesoscope_frames source directory is renamed.

        This function is configured to parallelize data transfer and verification to optimize runtime speeds where
        possible.

    Args:
        session_data: The SessionData instance for the processed session.
        remove_sources: Determines whether to remove the transferred mesoscope frame data from the ScanImagePC.
            Generally, it is recommended to remove source data to keep ScanImagePC disk usage low. Note, setting
            this to True will only mark the data for removal. The removal is carried out by the dedicated data purging
            function that runs at the end of the session data preprocessing sequence.
        verify_transfer_integrity: Determines whether to verify the integrity of the transferred data. This is
            performed before the source folder is marked for removal from the ScanImagePC if remove_sources is True.
    """
    # Uses the input SessionData instance to determine the path to the folder that stores raw mesoscope data on the
    # ScanImage PC.
    session_name = session_data.session_name
    source = mesoscope_data.scanimagepc_data.session_specific_path

    # If the source folder does not exist or is already marked for deletion by the ubiquitin marker, the mesoscope data
    # has already been pulled to the VRPC and there is no need to pull the frames again. In this case, returns early
    if not source.exists() or source.joinpath("ubiquitin.bin").exists():
        return

    # Otherwise, if the source exists and is not marked for deletion, pulls the frame to the target directory:

    # Precreates the temporary storage directory for the pulled data.
    destination = session_data.raw_data.raw_data_path.joinpath("raw_mesoscope_frames")
    ensure_directory_exists(destination)

    # Defines the set of extensions to look for when verifying source folder contents
    extensions = {"*.me", "*.tiff", "*.tif", "*.roi"}

    # Verifies that all required files are present on the ScanImage PC. This loop will run until the user ensures
    # all files are present or fail five times in a row.
    error = False
    for attempt in range(5):  # A maximum of 5 reattempts is allowed
        # Extracts the names of files stored in the source folder
        files: tuple[Path, ...] = tuple([path for ext in extensions for path in source.glob(ext)])
        file_names: tuple[str, ...] = tuple([file.name for file in files])
        error = False  # Resets the error tracker at the beginning of each cycle

        # Ensures the folder contains the MotionEstimator.me file
        if "MotionEstimator.me" not in file_names:
            message = (
                f"Unable to pull the mesoscope-acquired data from the ScanImage PC to the VRPC. The "
                f"'mesoscope_frames' ScanImage PC directory for the session {session_name} does not contain the "
                f"required MotionEstimator.me file."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            error = True

        # Ensures the folder contains the fov.roi file
        if "fov.roi" not in file_names:
            message = (
                f"Unable to pull the mesoscope-acquired data from the ScanImage PC to the VRPC. The "
                f"'mesoscope_frames' ScanImage PC directory for the session {session_name} does not contain the "
                f"required fov.roi file."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            error = True

        # Ensures the folder contains the zstack_00000_00001.tif file
        if "zstack_00000_00001.tif" not in file_names:
            message = (
                f"Unable to pull the mesoscope-acquired data from the ScanImage PC to the VRPC. The "
                f"'mesoscope_frames' ScanImage PC directory for the session {session_name} does not contain the "
                f"required zstack_00000_00001.tif file."
            )
            console.echo(message=message, level=LogLevel.ERROR)
            error = True

        # Since version 3.0.0, this runtime is designed to pull the mesoscope_data to VRPC even if it contains no TIFF
        # stacks. THis is to support processing window checking runtime data, which only generates the
        # MotionEstimator.me, the fov.roi, and the zstack_00000_00001.tif files.

        # Breaks the loop if all files are present
        if not error:
            break

        # Otherwise, waits for the user to move the files into the requested directory and continues the runtime
        message = (
            f"Unable to locate all required Mesoscope data files when pulling the session {session_name} data to the "
            f"VRPC. Move all requested files to the session-specific mesoscope_frames directory on the ScanImage PC "
            f"before continuing the runtime. Note, cycling through this message 5 times in a row will abort the "
            f"preprocessing with a RuntimeError."
        )
        console.echo(message=message, level=LogLevel.WARNING)
        input("Enter anything to continue: ")

    # If the user has repeatedly failed 5 attempts in a row, exits with a runtime error.
    if error:
        message = (
            "Failed 5 consecutive attempts to locate all required mesoscope frame files. Aborting mesoscope "
            "data processing and terminating the preprocessing runtime."
        )
        console.error(message=message, error=RuntimeError)

    # Removes all binary files from the source directory before transferring. This ensures that the directory
    # does not contain any marker files used during runtime.
    for bin_file in source.glob("*.bin"):
        bin_file.unlink(missing_ok=True)

    # Generates the checksum for the source folder if transfer integrity verification is enabled.
    if verify_transfer_integrity:
        calculate_directory_checksum(directory=source, num_processes=None, save_checksum=True)

    # Transfers the mesoscope frames data from the ScanImagePC to the local machine.
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
    """Loops over all multi-frame Mesoscope TIFF stacks acquired for the session, recompresses them using the Limited
    Error Raster Compression (LERC) scheme, and extracts ScanImage metadata.

    This function is used as a preprocessing step for mesoscope-acquired data that optimizes the size of raw images for
    long-term storage and streaming over the network. To do so, all stacks are re-encoded using LERC scheme, which
    achieves ~70% compression ratio, compared to the original frame stacks obtained from the mesoscope. Additionally,
    this function also extracts frame-variant and frame-invariant ScanImage metadata from raw stacks and saves it as
    efficiently encoded JSON (.json) and compressed numpy archive (.npz) files to minimize disk space usage.

    Notes:
        This function is specifically calibrated to work with TIFF stacks produced by the ScanImage matlab software.
        Critically, these stacks are named using '_' to separate acquisition and stack number from the rest of the
        file name, and the stack number is always found last, e.g.: 'Tyche-A7_2022_01_25_1_00001_00067.tif'. If the
        input TIFF files do not follow this naming convention, the function will not process them. Similarly, if the
        stacks do not contain ScanImage metadata, they will be excluded from processing.

        To optimize runtime efficiency, this function employs multiple processes to work with multiple TIFFs at the
        same time. Given the overall size of each image dataset, this function can run out of RAM if it is allowed to
        operate on the entire folder at the same time. To prevent this, disable verification, use fewer processes, or
        change the batch_size to load fewer frames in memory at the same time.

        In addition to frame compression and data extraction, this function also generates the ops.json configuration
        file. This file is used during suite2p cell registration, performed as part of our standard data processing
        pipeline.

        This function is purposefully designed to collapse data from multiple acquisitions stored inside the same
        directory into the same frame volume. This implementation was chosen based on the specific patterns of data
        acquisition in the Sun lab, where all data acquired for a single session is necessarily expected to belong to
        the same acquisition.

    Args:
        session_data: The SessionData instance for the processed session.
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
    # Resolves the path to the temporary directory used to store all mesoscope data before it is preprocessed
    image_directory = session_data.raw_data.raw_data_path.joinpath("raw_mesoscope_frames")

    # If the raw_mesoscope_frames directory does not exist, either the mesoscope frames are already processed or were
    # not acquired at all. Aborts processing early.
    if not image_directory.exists():
        return

    # Handles special acquisition files that need to be processed differently to the TIFF stacks. These files are
    # generated directly by the setupAcquisition() MATLAB function as part of preparing for the main experiment runtime.
    mesoscope_data = MesoscopeData(session_data=session_data)
    target_files = (
        image_directory.joinpath("MotionEstimator.me"),
        image_directory.joinpath("fov.roi"),
        image_directory.joinpath("zstack_00000_00001.tif"),
    )

    # If necessary, persists the MotionEstimator and the fov.roi files to the 'persistent data' folder of the processed
    # animal on the ScanImagePC.
    if not mesoscope_data.scanimagepc_data.roi_path.exists():
        sh.copy2(target_files[1], mesoscope_data.scanimagepc_data.roi_path)
    if not mesoscope_data.scanimagepc_data.motion_estimator_path.exists():
        sh.copy2(target_files[0], mesoscope_data.scanimagepc_data.motion_estimator_path)

    # Copies all files to the mesoscope_data directory without any further processing.
    sh.copy2(target_files[0], session_data.raw_data.mesoscope_data_path.joinpath("MotionEstimator.me"))
    sh.copy2(target_files[1], session_data.raw_data.mesoscope_data_path.joinpath("fov.roi"))
    # Renames to 'zstack.tiff'
    sh.copy2(target_files[2], session_data.raw_data.mesoscope_data_path.joinpath("zstack.tiff"))

    # Resolves the paths to the output directories and files
    output_directory = Path(session_data.raw_data.mesoscope_data_path)
    ensure_directory_exists(output_directory)  # Generates the directory
    frame_invariant_metadata_path = output_directory.joinpath("frame_invariant_metadata.json")
    frame_variant_metadata_path = output_directory.joinpath("frame_variant_metadata.npz")
    ops_path = output_directory.joinpath("ops.json")

    # Precreates the dictionary to store frame-variant metadata extracted from all TIFF frames before they are
    # compressed into BigTiff.
    all_metadata = defaultdict(list)

    # Finds all TIFF files in the input directory (non-recursive).
    tiff_files = list(image_directory.glob("*.tif")) + list(image_directory.glob("*.tiff"))

    # Sorts files naturally. Since all files use the _acquisition#_stack# format, this procedure should naturally
    # sort the data in the order of acquisition. This is used to serialize multiple acquisitions recorded as part of the
    # session into one continuous frame stack.
    tiff_files = natsorted(tiff_files)

    # Goes over each stack and, for each, determines the position of the first frame from the stack in the overall
    # sequence of frames acquired by all stacks. This is used to map frames stored in multiple stacks to a single
    # session-wide sequence.
    frame_numbers = []
    starting_frame = 1
    for file in tiff_files:
        if "session" in file.name:  # All valid mesoscope data files acquired in the lab are named 'session'.
            stack_size = _verify_and_get_stack_size(file)
            if stack_size > 0:
                # Appends the starting frame number to the list and increments the stack list
                frame_numbers.append(starting_frame)
                starting_frame += stack_size

        else:
            # Stack size of 0 suggests that the checked file is not a ScanImage TIFF stack, so it is removed from
            # processing. Also, all files other than 'session' are not considered for further processing since 3.0.0.
            tiff_files.remove(file)

    # Converts to tuple for efficiency
    tiff_files = tuple(tiff_files)
    frame_numbers = tuple(frame_numbers)

    # Ends the runtime early if there are no valid TIFF files to process after filtering
    if len(tiff_files) == 0:
        # If configured, the processing function ensures that the temporary image directory with all TIFF source files
        # is removed after processing.
        if remove_sources:
            delete_directory(image_directory)
        return

    # Extracts frame invariant metadata using the first frame of the first TIFF stack. Since this metadata is the
    # same for all stacks, it is safe to use any available stack. We use the first one for consistency with
    # suite2p helper scripts.
    _process_invariant_metadata(frame_stack_path=tiff_files[0], ops_path=ops_path, metadata_path=frame_invariant_metadata_path)

    # Uses partial to bind the constant arguments to the processing function
    process_func = partial(
        _process_stack,
        output_directory=output_directory,
        verify_integrity=verify_integrity,
        batch_size=batch_size,
    )

    # Processes each tiff stack in parallel
    with ProcessPoolExecutor(max_workers=num_processes) as executor:
        # Submits all tasks
        future_to_file = set()
        for file, frame in zip(tiff_files, frame_numbers):
            # noinspection PyTypeChecker
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

    # If configured, the processing function ensures that the temporary image directory with all TIFF source files is
    # removed after processing.
    if remove_sources:
        delete_directory(image_directory)


def _preprocess_log_directory(
    session_data: SessionData, num_processes: int, remove_sources: bool = True, verify_integrity: bool = False
) -> None:
    """Compresses all .npy (uncompressed) log entries stored in the behavior log directory into one or more .npz
    archives.

    This service function is used during data preprocessing to optimize the size and format used to store all log
    entries. Primarily, this is necessary to facilitate data transfer over the network and log processing on the
    BioHPC server.

    Args:
        session_data: The SessionData instance for the processed session.
        num_processes: The maximum number of processes to use while processing the directory.
        remove_sources: Determines whether to remove the original .npy files after they are compressed into .npz
            archives. It is recommended to have this option enabled.
        verify_integrity: Determines whether to verify the integrity of compressed data against the source data.
            It is advised to have this disabled for most runtimes, as data corruption is highly unlikely, but enabling
            this option adds a significant overhead to the processing time.

    Raises:
        RuntimeError: If the target log directory contains both compressed and uncompressed log entries.
    """
    # Resolves the path to the temporary log directory generated during runtime
    log_directory = Path(session_data.raw_data.raw_data_path).joinpath("behavior_data_log")

    # Aborts early if the log directory does not exist at all, for example, if working with Window checking sessions
    if not log_directory.exists():
        return

    # Searches for compressed and uncompressed files inside the log directory
    compressed_files: list[Path] = [file for file in log_directory.glob("*.npz")]
    uncompressed_files: list[Path] = [file for file in log_directory.glob("*.npy")]

    # If there are no uncompressed files, ends the runtime early
    if len(uncompressed_files) < 0:
        return

    # If the input directory contains .npy (uncompressed) log entries and no compressed log entries, compresses all log
    # entries in the directory
    if len(compressed_files) == 0 and len(uncompressed_files) > 0:
        assemble_log_archives(
            log_directory=log_directory,
            remove_sources=remove_sources,
            memory_mapping=False,
            verbose=True,
            verify_integrity=verify_integrity,
            max_workers=num_processes,
        )

    # If both compressed and uncompressed log files existing in the same directory, aborts with an error
    elif len(compressed_files) > 0 and len(uncompressed_files) > 0:
        message = (
            f"The temporary log directory for session {session_data.session_name} contains both compressed and "
            f"uncompressed log files. Since compression overwrites the .npz archive with the processed data, it is "
            f"unsafe to proceed with log compression in automated mode. Manually back up the existing .npz files, "
            f"remove them from the log directory and call the processing method again."
        )
        console.error(message, error=RuntimeError)

    # Renames the processed folder to behavior_data. Since behavior_data might already exist dues to SessionData
    # directory generation, removes any existing behavior_data directories before renaming the log folder.
    behavior_data_path = Path(session_data.raw_data.behavior_data_path)
    if behavior_data_path.exists():
        sh.rmtree(behavior_data_path)
    log_directory.rename(target=Path(session_data.raw_data.behavior_data_path))


def _resolve_telomere_marker(session_data: SessionData) -> None:
    """Reads the value of the 'incomplete' flag from the session's descriptor file and, if necessary, creates the
    telomere.bin marker.

    The telomere marker file is used by our data processing pipelines to determine whether to process the session.
    Incomplete sessions lacking telomere.bin are excluded from all further automated processing.

    Args:
        session_data: The SessionData instance for the processed session.
    """
    # Loads the session descriptor file to read the state of the 'incomplete' flag.
    descriptor_path = Path(session_data.raw_data.session_descriptor_path)
    descriptor: RunTrainingDescriptor | LickTrainingDescriptor | MesoscopeExperimentDescriptor
    if session_data.session_type == SessionTypes.LICK_TRAINING:
        descriptor = LickTrainingDescriptor.from_yaml(descriptor_path)
    elif session_data.session_type == SessionTypes.RUN_TRAINING:
        descriptor = RunTrainingDescriptor.from_yaml(descriptor_path)
    elif session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
        descriptor = MesoscopeExperimentDescriptor.from_yaml(descriptor_path)
    else:
        # Aborts early (without creating the telomere.bin marker file) for any other session type. This statically
        # ignores the descriptor of the Window Checking sessions, as all window checking sessions are considered
        # incomplete.
        return

    # If the session is complete, generates the telomere.bin marker file. Note, window checking sessions are
    # automatically considered 'incomplete' for the sake of data processing, as they do not contain any experiment
    # or behavior data that needs automated processing.
    if not descriptor.incomplete:
        session_data.raw_data.telomere_path.touch(exist_ok=True)


def _preprocess_google_sheet_data(session_data: SessionData) -> None:
    """Updates the water restriction log and the surgery_data.yaml file.

    This internal method is called as part of preprocessing. Primarily, it is used to ensure that each session folder
    contains the up-to-date information about the surgical intervention(s) performed on the animal before running the
    session. It also updates the water restriction log for the managed animal to reflect the water received before and
    after runtime.

    Args:
        session_data: The SessionData instance for the processed session.

    Raises:
        ValueError: If the session_type attribute of the input SessionData instance is not one of the supported options.
    """
    # Queries the data acquisition system configuration parameters.
    system_configuration = get_system_configuration()

    # Resolves the animal ID (name)
    animal_id = int(session_data.animal_id)

    # Loads the session descriptor file to read the data needed to update the wr log and determine whether to create
    # the telomere.bin marker
    descriptor_path = Path(session_data.raw_data.session_descriptor_path)
    descriptor: RunTrainingDescriptor | LickTrainingDescriptor | MesoscopeExperimentDescriptor
    quality: str | int = ""
    if session_data.session_type == SessionTypes.LICK_TRAINING:
        descriptor = LickTrainingDescriptor.from_yaml(descriptor_path)
    elif session_data.session_type == SessionTypes.RUN_TRAINING:
        descriptor = RunTrainingDescriptor.from_yaml(descriptor_path)
    elif session_data.session_type == SessionTypes.MESOSCOPE_EXPERIMENT:
        descriptor = MesoscopeExperimentDescriptor.from_yaml(descriptor_path)
    elif session_data.session_type == SessionTypes.WINDOW_CHECKING:
        window_descriptor: WindowCheckingDescriptor = WindowCheckingDescriptor.from_yaml(descriptor_path)

        # Ensures that the quality is always between 0 and 3 inclusive
        quality = int(np.clip(np.uint8(window_descriptor.surgery_quality), a_min=np.uint8(0), a_max=np.uint8(3)))
    else:
        message = (
            f"Unable to extract the water restriction data from the session descriptor file for session "
            f"{session_data.session_name}. Expected the session_type field of the SessionData instance to be one of "
            f"the supported options (lick training, run training, mesoscope experiment, or window checking) but "
            f"instead encountered {session_data.session_type}."
        )
        console.error(message, error=ValueError)

        # This should not be reachable, it is here to appease mypy.
        raise ValueError(message)  # pragma: no cover

    # Only carries out water restriction log processing and telomere.bin creation if the code above did not resolve
    # the quality level
    if quality == "":
        # Calculates the total volume of water, in ml, the animal received during and after the session
        # noinspection PyUnboundLocalVariable
        training_water = round(descriptor.dispensed_water_volume_ml, ndigits=3)
        experimenter_water = round(descriptor.experimenter_given_water_volume_ml, ndigits=3)
        total_water = training_water + experimenter_water

        # Connects to the WR sheet and generates the new water restriction log entry
        wr_sheet = WaterLog(
            session_date=session_data.session_name,
            animal_id=animal_id,
            credentials_path=Path(system_configuration.paths.google_credentials_path),
            sheet_id=system_configuration.sheets.water_log_sheet_id,
        )

        wr_sheet.update_water_log(
            weight=descriptor.mouse_weight_g,
            water_ml=total_water,
            experimenter_id=descriptor.experimenter,
            session_type=session_data.session_type,
        )

        message = "Water restriction log entry: Written."
        console.echo(message=message, level=LogLevel.SUCCESS)

    # Loads the surgery log Google Sheet file
    sl_sheet = SurgeryLog(
        project_name=session_data.project_name,
        animal_id=animal_id,
        credentials_path=Path(system_configuration.paths.google_credentials_path),
        sheet_id=system_configuration.sheets.surgery_sheet_id,
    )

    # If the surgery quality value was obtained above, updates the surgery quality column value with the provided value
    if quality != "":
        sl_sheet.update_surgery_quality(quality=int(quality))

        message = "Surgery quality: Updated."
        console.echo(message=message, level=LogLevel.SUCCESS)

    # Extracts the surgery data from the Google sheet file
    data: SurgeryData = sl_sheet.extract_animal_data()

    # Saves the data as a .yaml file to the session directory
    data.to_yaml(Path(session_data.raw_data.surgery_metadata_path))

    message = "Surgery data snapshot: Saved."
    console.echo(message=message, level=LogLevel.SUCCESS)


def _push_data(
    session_data: SessionData,
    parallel: bool = True,
    num_threads: int = 15,
) -> None:
    """Copies the raw_data directory from the VRPC to the NAS and the BioHPC server.

    This internal method is called as part of preprocessing to move the preprocessed data to the NAS and the server.
    This method generates the xxHash3-128 checksum for the source folder that the server processing pipeline uses to
    verify the integrity of the transferred data.

    Args:
        session_data: The SessionData instance for the processed session.
        parallel: Determines whether to parallelize the data transfer. When enabled, the method will transfer the
            data to all destinations at the same time (in parallel). Note, this argument does not affect the number
            of parallel threads used by each transfer process or the number of threads used to compute the
            xxHash3-128 checksum. This is determined by the 'num_threads' argument (see below). Note; each parallel
            process can use as many threads as specified by 'num_threads' at the same time.
        num_threads: Determines the number of threads used by each transfer process to copy the files and calculate
            the xxHash3-128 checksums. Since each process uses the same number of threads, it is highly
            advised to set this value so that num_threads * 2 (number of destinations) does not exceed the total
            number of CPU cores - 4.
    """
    # Uses SessionData to get the paths to remote destinations
    mesoscope_data = MesoscopeData(session_data)
    destinations = (
        Path(mesoscope_data.destinations.nas_data_path),
        Path(mesoscope_data.destinations.server_data_path),
    )

    # Computes the xxHash3-128 checksum for the source folder
    target = Path(session_data.raw_data.raw_data_path)
    calculate_directory_checksum(directory=target, num_processes=None, save_checksum=True)

    # If the method is configured to transfer files in parallel, submits tasks to a ProcessPoolExecutor
    if parallel:
        with ProcessPoolExecutor(max_workers=len(destinations)) as executor:
            futures = {
                executor.submit(
                    transfer_directory,
                    source=target,
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
                source=target,
                destination=destination,
                num_threads=num_threads,
                verify_integrity=False,  # This is now done on the server directly
            )


def rename_mesoscope_directory(session_data: SessionData) -> None:
    """This function renames the 'shared' mesoscope_data directory to use the name specific to the target session.

    Since this is an essential step for the preprocessing pipeline to discover and pull the mesoscope data to VRPC
    during preprocessing, it has to be done before running the mesoscope data preprocessing. Ideally, this function
    should be called by the MesoscopeVRSystem stop() method, but it is also called by the preprocessing pipeline's
    main function.
    """
    mesoscope_data = MesoscopeData(session_data)
    # If necessary, renames the 'shared' mesoscope_data directory to use the name specific to the preprocessed session.
    # It is essential that this is done before preprocessing, as the preprocessing pipeline uses this semantic for
    # finding and pulling the mesoscope data for the processed session.
    general_path = mesoscope_data.scanimagepc_data.mesoscope_data_path
    session_specific_path = mesoscope_data.scanimagepc_data.session_specific_path

    # Note, the renaming only happens if the session-specific cache does not exist, the general mesoscope_frames cache
    # exists, and it is not empty (has files inside).
    if (
        not session_specific_path.exists()
        and general_path.exists()
        and len([path for path in general_path.glob("*")]) > 0
    ):
        general_path.rename(session_specific_path)
        ensure_directory_exists(general_path)  # Generates a new empty mesoscope_frames directory


def preprocess_session_data(session_data: SessionData) -> None:
    """Aggregates all data on VRPC, compresses it for efficient network transmission, safely transfers the data to the
    BioHPC server and the Synology NAS for long-term storage, and removes all local data copies.

    This method should be called at the end of each training and experiment runtime to preprocess the data. Primarily,
    it prepares the data for further processing, moves it to appropriate long-term storage destinations, and keeps the
    VRPC and ScanImagePC filesystem free from clutter by removing redundant local data copies.

    Args:
        session_data: The SessionData instance for the processed session.
    """
    message = f"Initializing session {session_data.session_name} data preprocessing..."
    console.echo(message=message, level=LogLevel.INFO)

    # If necessary, ensures that the mesoscope_data ScanImagePC directory is renamed to include the processed session
    # name.
    rename_mesoscope_directory(session_data=session_data)

    # Compresses all log entries (.npy) into archive files (.npz)
    _preprocess_log_directory(session_data=session_data, num_processes=31, remove_sources=True, verify_integrity=False)

    # Renames all videos to use human-friendly names
    _preprocess_video_names(session_data=session_data)

    # Pulls mesoscope-acquired data from the ScanImagePC to the VRPC
    _pull_mesoscope_data(
        session_data=session_data,
        num_threads=31,
        remove_sources=True,
        verify_transfer_integrity=False,
    )

    # Compresses all mesoscope-acquired frames and extracts their metadata
    _preprocess_mesoscope_directory(
        session_data=session_data,
        num_processes=31,
        remove_sources=True,
        verify_integrity=True,
        batch_size=100,
    )

    # Extracts and saves the surgery data to the metadata directories and writes the water restriction log data
    # for the animal
    _preprocess_google_sheet_data(session_data=session_data)

    # Checks whether the session data is complete and, if so, generates a telomere.bin marker file. This is used during
    # processing to automatically exclude incomplete sessions.
    _resolve_telomere_marker(session_data=session_data)

    # Sends preprocessed data to the NAS and the BioHPC server
    _push_data(
        session_data=session_data,
        parallel=True,
        num_threads=15,
    )

    # Purges all redundant data from the ScanImagePC and the VRPC
    purge_redundant_data()

    message = f"Session {session_data.session_name} data preprocessing: Complete."
    console.echo(message=message, level=LogLevel.SUCCESS)


def purge_redundant_data() -> None:
    """Loops over ScanImagePC and VRPC directories that store training and experiment data and removes no longer
    necessary data caches.

    This function searches the ScanImagePC and VRPC for no longer necessary directories and removes them from the
    respective systems. ScanImagePC directories are marked for deletion once they are safely copied to the VRPC. VRPC
    directories are marked for deletion once the data is safely copied to the BioHPC server. Both copying steps include
    verifying the integrity of the transferred data using xxHash-128 checksums.

    Notes:
        This is a service function intended to maintain the ScanImagePC and VRPC disk space. Once the data is moved to
        the BioHPC server and the NAS, it is generally safe to remove the copies stored on the ScanImagePC and VRPC.

        Currently, this function does not discriminate between projects or animals. It will remove all data marked for
        deletion via the ubiquitin.bin markers.
    """
    message = "Initializing redundant data purging..."
    console.echo(message=message, level=LogLevel.INFO)

    # Uses the Mesoscope-VR system configuration file to resolve the paths to the root ScanImagePc and VRPC directories.
    system_configuration = get_system_configuration()
    root_paths = [system_configuration.paths.mesoscope_directory, system_configuration.paths.root_directory]

    # Recursively searches both root directories for folders marked for deletion by ubiquitin.bin marker files.
    deletion_candidates = [file.parent for root_path in root_paths for file in root_path.rglob("ubiquitin.bin")]

    # If there are no deletion candidates, returns without further processing
    if len(deletion_candidates) == 0:
        message = "No redundant data to purge. Runtime: Complete."
        console.echo(message=message, level=LogLevel.SUCCESS)
        return

    # Removes all discovered redundant data directories
    for candidate in tqdm(deletion_candidates, desc="Deleting redundant data directories", unit="directory"):
        # If the deletion candidate is a 'raw_data' session directory, escalates the deletion to remove the entire
        # session directory.
        if candidate.name == "raw_data":
            candidate = candidate.parent
        delete_directory(directory_path=candidate)

    message = "Redundant data purging: Complete"
    console.echo(message=message, level=LogLevel.SUCCESS)


def purge_failed_session(session_data: SessionData) -> None:
    """Removes all data and directories associated with the input session.

    This function is extremely dangerous and should be used with caution. It is designed to remove all data from failed
    or no longer necessary sessions. Never use this function on sessions that contain valid scientific data.

    Args:
        session_data: The SessionData instance for the session whose data needs to be removed.
    """
    # If a session does not contain the nk.bin marker, this suggests that it was able to successfully initialize the
    # runtime and likely contains valid data. IN this case, asks the user to confirm they intend to proceed with the
    # deletion. Sessions with nk.bin markers are considered safe for removal at all times.
    if not session_data.raw_data.nk_path.exists():
        message = (
            f"Preparing to remove all data for session {session_data.session_name} from animal "
            f"{session_data.animal_id}. Warning, this process is NOT reversible and removes ALL session data. Are you "
            f"sure you want to proceed?"
        )
        console.echo(message=message, level=LogLevel.WARNING)

        # Locks and waits for user response
        while True:
            answer = input("Enter 'yes' (to proceed) or 'no' (to abort): ")

            # Continues with the deletion
            if answer.lower() == "yes":
                break

            # Aborts without deleting
            if answer.lower() == "no":
                message = f"Session {session_data.session_name} data purging: Aborted"
                console.echo(message=message, level=LogLevel.SUCCESS)
                return

    # Uses MesoscopeData to query the paths to all known session data directories. This includes the directories on the
    # NAS and the BioHPC server.
    mesoscope_data = MesoscopeData(session_data)
    deletion_candidates = [
        session_data.raw_data.raw_data_path.parent,
        mesoscope_data.destinations.nas_data_path.parent,
        mesoscope_data.destinations.server_data_path.parent,
        mesoscope_data.destinations.server_processed_data_path.parent,
        mesoscope_data.scanimagepc_data.session_specific_path,
    ]

    # Removes all session-specific data directories from all destinations
    for candidate in tqdm(deletion_candidates, desc="Deleting session directories", unit="directory"):
        delete_directory(directory_path=candidate)

    # Ensures that the mesoscope_data directory is reset, in case it has any lingering from the purged runtime.
    for file in mesoscope_data.scanimagepc_data.mesoscope_data_path.glob("*"):
        file.unlink(missing_ok=True)

    message = "Session data purging: Complete"
    console.echo(message=message, level=LogLevel.SUCCESS)


def migrate_animal_between_projects(animal: str, source_project: str, target_project: str) -> None:
    """Moves all sessions for the target animal from the source project to the target project.

    This function is primarily used when animals are moved from the shared 'TestMice' project to a user-specific
    project. It transfers all available data for the target animal across all destinations, based on the list of
    sessions stored on the remote server. Any session that has not yet been transferred to the server is excluded from
    the migration process and will remain on the local acquisition system PC.

    Args:
        animal: The animal for which to migrate the data.
        source_project: The name of the project from which to migrate the data.
        target_project: The name of the project to which the data should be migrated.
    """
    console.echo(f"Migrating animal {animal} from project {source_project} to project {target_project}...")

    # Queries the system configuration parameters, which includes the paths to all filesystems used to store project
    # data
    system_configuration = get_system_configuration()

    # The two main directories used in the migration process are the server storage directory (source) and the
    # local acquisition-system PC project directory (destination)
    source_server_root = system_configuration.paths.server_storage_directory.joinpath(source_project, animal)
    destination_local_root = system_configuration.paths.root_directory.joinpath(target_project, animal)

    # Also resolves the path to the local animal root. This is used when processing sessions to purge migrated sessions
    # from the source project
    source_local_root = system_configuration.paths.root_directory.joinpath(source_project, animal)

    # If the target project does not exist, aborts with an error (analogous to how creating de-novo animal
    # datastructures is handled)
    if not destination_local_root.parent.exists():
        message = (
            f"Unable to migrate the animal {animal} from project {source_project} to project {target_project}. The "
            f"target project does not exist. Use the 'sl-create-project' command to create the project before "
            f"migrating animals to this project."
        )
        console.error(message=message, error=FileNotFoundError)

    # Ensures that the root directory for the processed animal exists on the local machine.
    ensure_directory_exists(destination_local_root)

    # Ensures that all locally stored sessions have been processed and moved to the BioHPC server for storage. This is
    # a prerequisite to ensure that all data is properly migrated from the source project to the target project.
    local_sessions = [file.parents[1] for file in source_local_root.rglob("*session_data.yaml")]
    if len(local_sessions) > 0:
        message = (
            f"Unable to migrate the animal {animal} from project {source_project} to project {target_project}. The "
            f"source project directory on the local acquisition-system PC contains non-preprocessed session data. "
            f"Preprocess all locally stored sessions before starting the migration process."
        )
        console.error(message=message, error=FileNotFoundError)

    # Loops over all sessions stored on the server and processes them sequentially
    sessions = [file.parents[1] for file in source_server_root.rglob("*session_data.yaml")]
    for session in sessions:
        console.echo(f"Migrating session {session.name}...")
        local_session_path = destination_local_root.joinpath(session.name)
        remote_session_path = source_server_root.joinpath(session.name)

        # Pulls the session to the local machine. The data is pulled into the target project's directory structure.
        ensure_directory_exists(destination_local_root)
        transfer_directory(
            source=remote_session_path, destination=local_session_path, num_threads=30, verify_integrity=False
        )

        # Copies the session_data.yaml file from the pulled directory to the old local directory for the processed
        # session. This is then used to remove old session data from all destinations.
        new_sd_path = local_session_path.joinpath("raw_data", "session_data.yaml")
        old_sd_path = source_local_root.joinpath(session.name, "raw_data", "session_data.yaml")
        ensure_directory_exists(old_sd_path)  # Since preprocessing removes the raw_data directory, this recreates it
        sh.copy2(src=new_sd_path, dst=old_sd_path)

        # Modifies the SessionData instance for the pulled session to use the new project name and the new session data
        # location
        session_data = SessionData.load(session_path=local_session_path)
        session_data.project_name = target_project
        session_data.raw_data.session_data_path = new_sd_path
        session_data.save()

        # Reloads session data to apply the changes
        session_data = SessionData.load(session_path=local_session_path)

        # Runs preprocessing on the session data again, which regenerates the checksum and transfers the data to
        # the long-term storage destinations.
        preprocess_session_data(session_data=session_data)

        # Removes now-obsolete server, NAS, and local machine directories. To do so, first marks the old session for
        # deletion by creating the 'nk.bin' marker and then calls the purge pipeline on that session.
        old_session_data = SessionData.load(session_path=old_sd_path.parents[1])
        old_session_data.raw_data.nk_path.touch()
        purge_failed_session(old_session_data)

    console.echo("Migrating persistent data directories...")
    # Moves ScanImagePC persistent data for the animal between projects This preserves existing MotionEstimator and ROI
    # data, if any was resolved for any processed session
    old = system_configuration.paths.mesoscope_directory.joinpath(source_project, animal)
    new = system_configuration.paths.mesoscope_directory.joinpath(target_project, animal)
    sh.rmtree(new)
    sh.move(src=old, dst=new)

    # Also moves the VRPC persistent data for the animal between projects.
    old = source_local_root.joinpath("persistent_data")
    new = destination_local_root.joinpath("persistent_data")
    sh.rmtree(new)
    sh.move(src=old, dst=new)

    # Removes the old animal directory from all destinations. This also removes any lingering data not moved during
    # the migration process. This ensures that each animal is found under at most a single project directory on all
    # destinations.
    deletion_candidates = [
        system_configuration.paths.mesoscope_directory.joinpath(source_project, animal),
        system_configuration.paths.nas_directory.joinpath(source_project, animal),
        system_configuration.paths.root_directory.joinpath(source_project, animal),
        system_configuration.paths.server_storage_directory.joinpath(source_project, animal),
        system_configuration.paths.server_working_directory.joinpath(source_project, animal),
    ]
    for candidate in tqdm(deletion_candidates, desc="Deleting redundant animal directories", unit="directory"):
        delete_directory(directory_path=candidate)

    # Note, this process intentionally preserves the now-empty animal directory in the original project to keep the
    # animal project history.
    console.echo("Migration: Complete.", level=LogLevel.SUCCESS)
