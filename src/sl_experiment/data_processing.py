"""This module provides the methods used to process experimental data after acquisition. The primary purpose of this
processing is to prepare the data for storage and further processing in the Sun lab data cluster. Some functions from
this module are called from the Sun Lab data cluster.
"""

import os
import json
import shutil as sh
from typing import Any
from pathlib import Path
from datetime import datetime
from functools import partial
from collections import defaultdict
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed, ThreadPoolExecutor

from tqdm import tqdm
import numpy as np
import polars as pl
import tifffile
from numpy.typing import NDArray
from numpy.lib.npyio import NpzFile
from ataraxis_video_system import extract_logged_video_system_data
from ataraxis_base_utilities import console, ensure_directory_exists, LogLevel
from ataraxis_data_structures import DataLogger, YamlConfig

from .module_interfaces import (
    TTLInterface,
    LickInterface,
    BreakInterface,
    ValveInterface,
    ScreenInterface,
    TorqueInterface,
    EncoderInterface,
)
from .packaging_tools import calculate_directory_checksum
from .transfer_tools import transfer_directory


# This has to be defined here to avoid circular import in experiment.py
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
    cm_per_pulse: np.float64 | None = None
    """EncoderInterface instance property."""
    maximum_break_strength: np.float64 | None = None
    """BreakInterface instance property."""
    minimum_break_strength: np.float64 | None = None
    """BreakInterface instance property."""
    # noinspection PyUnresolvedReferences
    lick_threshold: None | np.uint16 = None
    """BreakInterface instance property."""
    scale_coefficient: np.float64 | None = None
    """ValveInterface instance property."""
    nonlinearity_exponent: np.float64 | None = None
    """ValveInterface instance property."""
    torque_per_adc_unit: np.float64 | None = None
    """TorqueInterface instance property."""
    initially_on: bool | None = None
    """ScreenInterface instance property."""
    has_ttl: bool | None = None
    """TTLInterface instance property."""


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
    subdirs = [p for p in directory_path.iterdir() if p.is_dir()]

    # Deletes files in parallel
    with ThreadPoolExecutor() as executor:
        executor.map(os.unlink, files)

    # Recursively deletes subdirectories
    for subdir in subdirs:
        _delete_directory(subdir)

    # Removes the now-empty directory
    os.rmdir(directory_path)


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


def _process_camera_timestamps(log_path: Path, output_path: Path) -> None:
    """Reads the log .npz archive specified by the log_path and extracts the camera frame timestamps
    as a Polars Series saved to the output_path as a Feather file.

    Args:
        log_path: Path to the .npz log archive to be parsed.
        output_path: Path to save the output Polars Series as a Feather file.
    """
    # Extracts timestamp data from log archive
    timestamp_data = extract_logged_video_system_data(log_path)

    # Converts extracted data to Polars series.
    timestamps_series = pl.Series(name="frame_time_us", values=timestamp_data)

    # Saves extracted data using Feather format and 'lz4' compression. Lz4 allows optimizing processing time and
    # file size. These extracted files are temporary and will be removed during later processing steps.
    timestamps_series.to_frame().write_ipc(file=output_path, compression="lz4")


def _process_experiment_data(log_path: Path, output_directory: Path, cue_map: dict[int, float]) -> None:
    """Extracts the VR states, Experiment states, and the Virtual Reality cue sequence from the log generated
    by the MesoscopeExperiment instance during runtime and saves the extracted data as Polars DataFrame .feather files.

    This extraction method functions similar to camera log extraction and hardware module log extraction methods. The
    key difference is the wall cue sequence extraction, which does not have a timestamp column. Instead, it has a
    distance colum which stores the distance the animal has to run, in centimeters, to reach each cue in the sequence.
    It is expected that during data processing, the distance data will be used to align the cues to the distance ran by
    the animal during the experiment.
    """
    # Loads the archive into RAM
    archive: NpzFile = np.load(file=log_path)

    # Precreates the variables used to store extracted data
    vr_states = []
    vr_timestamps = []
    experiment_states = []
    experiment_timestamps = []
    cue_sequence: NDArray[np.uint8] = np.zeros(shape=0, dtype=np.uint8)

    # Locates the logging onset timestamp. The onset is used to convert the timestamps for logged data into absolute
    # UTC timestamps. Originally, all timestamps other than onset are stored as elapsed time in microseconds
    # relative to the onset timestamp.
    timestamp_offset = 0
    onset_us = np.uint64(0)
    timestamp: np.uint64
    for number, item in enumerate(archive.files):
        message: NDArray[np.uint8] = archive[item]  # Extracts message payload from the compressed .npy file

        # Recovers the uint64 timestamp value from each message. The timestamp occupies 8 bytes of each logged
        # message starting at index 1. If timestamp value is 0, the message contains the onset timestamp value
        # stored as 8-byte payload. Index 0 stores the source ID (uint8 value)
        if np.uint64(message[1:9].view(np.uint64)[0]) == 0:
            # Extracts the byte-serialized UTC timestamp stored as microseconds since epoch onset.
            onset_us = np.uint64(message[9:].view("<i8")[0].copy())

            # Breaks the loop onc the onset is found. Generally, the onset is expected to be found very early into
            # the loop
            timestamp_offset = number  # Records the item number at which the onset value was found.
            break

    # Once the onset has been discovered, loops over all remaining messages and extracts data stored in these
    # messages.
    for item in archive.files[timestamp_offset + 1 :]:
        message = archive[item]

        # Extracts the elapsed microseconds since timestamp and uses it to calculate the global timestamp for the
        # message, in microseconds since epoch onset.
        elapsed_microseconds = np.uint64(message[1:9].view(np.uint64)[0].copy())
        timestamp = onset_us + elapsed_microseconds

        payload = message[9:]  # Extracts the payload from the message

        # If the message is longer than 500 bytes, it is a sequence of wall cues. It is very unlikely that we
        # will log any other data with this length, so it is a safe heuristic to use.
        if len(payload) > 500:
            cue_sequence = payload.view(np.uint8).copy()  # Keeps the original numpy uint8 format

        # If the message has a length of 2 bytes and the first element is 1, the message communicates the VR state
        # code.
        elif len(payload) == 2 and payload[0] == 1:
            vr_state = np.uint8(payload[1])  # Extracts the VR state code from the second byte of the message.
            vr_states.append(vr_state)
            vr_timestamps.append(timestamp)

        # Otherwise, if the starting code is 2, the message communicates the experiment state code.
        elif len(payload) == 2 and payload[0] == 2:
            # Extracts the experiment state code from the second byte of the message.
            experiment_state = np.uint8(payload[1])
            experiment_states.append(experiment_state)
            experiment_timestamps.append(timestamp)

    # Closes the archive to free up memory
    archive.close()

    # Uses the cue_map dictionary to compute the length of each cue in the sequence. Then computes the cumulative
    # distance the animal needs to travel to reach each cue in the sequence. The first cue is associated with distance
    # of 0 (the animal starts at this cue), the distance to each following cue is the sum of all previous cue lengths.
    distance_sequence = np.zeros(len(cue_sequence), dtype=np.float64)
    distance_sequence[1:] = np.cumsum([cue_map[int(code)] for code in cue_sequence[:-1]], dtype=np.float64)

    # Converts extracted data into Polar Feather files:
    vr_dataframe = pl.DataFrame(
        {
            "time_us": vr_timestamps,
            "vr_state": vr_states,
        }
    )
    exp_dataframe = pl.DataFrame(
        {
            "time_us": experiment_timestamps,
            "experiment_state": experiment_states,
        }
    )
    cue_dataframe = pl.DataFrame(
        {
            "vr_cue": cue_sequence,
            "traveled_distance_cm": distance_sequence,
        }
    )

    # Saves the DataFrames to Feather file with lz4 compression
    vr_dataframe.write_ipc(output_directory.joinpath("vr_data.feather"), compression="lz4")
    exp_dataframe.write_ipc(output_directory.joinpath("experiment_data.feather"), compression="lz4")
    cue_dataframe.write_ipc(output_directory.joinpath("cue_data.feather"), compression="lz4")


def process_log_directory(data_directory: Path, verbose: bool = False) -> None:
    """Reads the compressed .npz log files stored in the input directory and extracts all camera frame timestamps and
    relevant behavior data stored in log files.

    This function is intended to run on the BioHPC server as part of the data processing pipeline. It is optimized to
    process all log files in parallel and extract the data stored inside the files into behavior_data directory and
    camera_frames directory.

    Notes:
        This function makes certain assumptions about the layout of the raw-data directory to work as expected.

    Args:
        data_directory: The Path to the target session raw_data directory to be processed.
        verbose: Determines whether this function should run in the verbose mode.
    """
    # Resolves the paths to the specific directories used during processing
    log_directory = data_directory.joinpath("behavior_data_log")  # Should exist inside the raw data directory
    camera_frame_directory = data_directory.joinpath("camera_frames")  # Should exist inside the raw data directory
    behavior_data_directory = data_directory.joinpath("behavior_data")
    ensure_directory_exists(behavior_data_directory)  # Generates the directory

    # Should exist inside the raw data directory
    hardware_configuration_path = data_directory.joinpath("hardware_configuration.yaml")

    # Finds all .npz log files inside the input log file directory. Assumes there are no uncompressed log files.
    compressed_files: list[Path] = [file for file in log_directory.glob("*.npz")]

    # Loads the input HardwareConfiguration file to read the hardware parameters necessary to parse the data
    hardware_configuration: RuntimeHardwareConfiguration = RuntimeHardwareConfiguration.from_yaml(  # type: ignore
        file_path=hardware_configuration_path,
    )

    # Otherwise, iterates over all compressed log files and processes them in-parallel
    with ProcessPoolExecutor() as executor:
        futures = set()
        for file in compressed_files:
            # MesoscopeExperiment log file
            if file.stem == "1_log" and hardware_configuration.cue_map is not None:
                futures.add(
                    executor.submit(
                        _process_experiment_data,
                        file,
                        behavior_data_directory,
                        hardware_configuration.cue_map,
                    )
                )

            # Face Camera timestamps
            if file.stem == "51_log":
                futures.add(
                    executor.submit(
                        _process_camera_timestamps,
                        file,
                        camera_frame_directory.joinpath("face_camera_timestamps.feather"),
                    )
                )

            # Left Camera timestamps
            if file.stem == "62_log":
                futures.add(
                    executor.submit(
                        _process_camera_timestamps,
                        file,
                        camera_frame_directory.joinpath("left_camera_timestamps.feather"),
                    )
                )

            # Right Camera timestamps
            if file.stem == "73_log":
                futures.add(
                    executor.submit(
                        _process_camera_timestamps,
                        file,
                        camera_frame_directory.joinpath("right_camera_timestamps.feather"),
                    )
                )

            # Actor AMC module data
            if file.stem == "101_log":
                # Break
                if (
                    hardware_configuration.minimum_break_strength is not None
                    and hardware_configuration.maximum_break_strength is not None
                ):
                    futures.add(
                        executor.submit(
                            BreakInterface.parse_logged_data,
                            file,
                            behavior_data_directory,
                            hardware_configuration.minimum_break_strength,
                            hardware_configuration.maximum_break_strength,
                        )
                    )

                # Valve
                if (
                    hardware_configuration.nonlinearity_exponent is not None
                    and hardware_configuration.scale_coefficient is not None
                ):
                    futures.add(
                        executor.submit(
                            ValveInterface.parse_logged_data,
                            file,
                            behavior_data_directory,
                            hardware_configuration.scale_coefficient,
                            hardware_configuration.nonlinearity_exponent,
                        )
                    )

                # Screens
                if hardware_configuration.initially_on is not None:
                    futures.add(
                        executor.submit(
                            ScreenInterface.parse_logged_data,
                            file,
                            behavior_data_directory,
                            hardware_configuration.initially_on,
                        )
                    )

            # Sensor AMC module data
            if file.stem == "152_log":
                # Lick Sensor
                if hardware_configuration.lick_threshold is not None:
                    futures.add(
                        executor.submit(
                            LickInterface.parse_logged_data,
                            file,
                            behavior_data_directory,
                            hardware_configuration.lick_threshold,
                        )
                    )

                # Torque Sensor
                if hardware_configuration.torque_per_adc_unit is not None:
                    futures.add(
                        executor.submit(
                            TorqueInterface.parse_logged_data,
                            file,
                            behavior_data_directory,
                            hardware_configuration.torque_per_adc_unit,
                        )
                    )

                # Mesoscope Frame TTL module
                if hardware_configuration.has_ttl:
                    futures.add(executor.submit(TTLInterface.parse_logged_data, file, behavior_data_directory))

            # Encoder AMC module data
            if file.stem == "203_log":
                # Encoder
                if hardware_configuration.cm_per_pulse is not None:
                    futures.add(
                        executor.submit(
                            EncoderInterface.parse_logged_data,
                            file,
                            behavior_data_directory,
                            hardware_configuration.cm_per_pulse,
                        )
                    )

        # Displays a progress bar to track the parsing status if the function is called in the verbose mode.
        if verbose:
            with tqdm(
                total=len(futures),
                desc=f"Parsing log sources",
                unit="source",
            ) as pbar:
                for future in as_completed(futures):
                    # Propagates any exceptions from the transfers
                    future.result()
                    pbar.update(1)
        else:
            for future in as_completed(futures):
                # Propagates any exceptions from the transfers
                future.result()


def _preprocess_video_names(raw_data_directory: Path) -> None:
    """Renames the video files generated during runtime to use human-friendly camera names, rather than ID-codes.

    This is a minor preprocessing function primarily designed to make further data processing steps more human-readable.

    Notes:
        This function assumes that the runtime uses 3 cameras with IDs 51 (face camera), 62 (left camera), and 73
        (right camera).

    Args:
        raw_data_directory: The Path to the target session raw_data directory to be processed.
    """

    # Resolves the path to the camera frame directory
    camera_frame_directory = raw_data_directory.joinpath("camera_frames")

    # Renames the video files to use human-friendly names. Assumes the standard data acquisition configuration with 3
    # cameras and predefined camera IDs.
    os.renames(
        old=camera_frame_directory.joinpath("051.mp4"),
        new=camera_frame_directory.joinpath("face_camera.mp4"),
    )
    os.renames(
        old=camera_frame_directory.joinpath("062.mp4"),
        new=camera_frame_directory.joinpath("left_camera.mp4"),
    )
    os.renames(
        old=camera_frame_directory.joinpath("073.mp4"),
        new=camera_frame_directory.joinpath("right_camera.mp4"),
    )


def _pull_mesoscope_data(
    raw_data_directory: Path,
    mesoscope_root_directory: Path,
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
        raw_data_directory: The Path to the target session raw_data directory to be processed.
        mesoscope_root_directory: The Path to the root directory that stores all experiment data on the ScanImagePC.
        num_threads: The number of parallel threads used for transferring the data from ScanImage (mesoscope) PC to
            the local machine.
        remove_sources: Determines whether to remove the transferred mesoscope frame data from the ScanImagePC.
            Generally, it is recommended to remove source data to keep ScanImagePC disk usage low. Note, setting
            this to True will only mark the data for removal. The data will not be removed until 'purge-data' command
            is used from the terminal.
        verify_transfer_integrity: Determines whether to verify the integrity of the transferred data. This is
            performed before source folder is marked for removal from the ScanImagePC if remove_sources is True.
    """
    # Overall, the path to raw_data folder looks like this: root/project/animal/session/raw_data. This indexes the
    # session, project, and animal names from the path.
    session_name = raw_data_directory.parents[0].name
    animal_name = raw_data_directory.parents[1].name
    project_name = raw_data_directory.parents[2].name

    # Uses the session name to determine the path to the folder that stores raw mesoscope data on the ScanImage PC.
    source = mesoscope_root_directory.joinpath(f"{session_name}_mesoscope_frames")

    # If the source folder does not exist or is already marked for deletion by the ubiquitin marker, the mesoscope data
    # has already been pulled to the VRPC and there is no need to pull the frames again. In this case, returns early
    if not source.exists() or source.joinpath("ubiquitin.bin").exists():
        return

    # Otherwise, if the source exists and is not marked for deletion, pulls the frame to the target directory:

    # Precreates the temporary storage directory for the pulled data.
    destination = raw_data_directory.joinpath("raw_mesoscope_frames")
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
    persistent_motion_estimator_path = mesoscope_root_directory.joinpath(
        "persistent_data", project_name, animal_name, "MotionEstimator.me"
    )
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
    raw_data_directory: Path,
    num_processes: int,
    remove_sources: bool = True,
    batch: bool = False,
    verify_integrity: bool = True,
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
        raw_data_directory: The Path to the target session raw_data directory to be processed.
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
    image_directory = raw_data_directory.joinpath("raw_mesoscope_frames")  # Should exist inside the raw data directory
    output_directory = raw_data_directory.joinpath("mesoscope_frames")
    ensure_directory_exists(output_directory)  # Generates the directory

    # Also resolves paths to the output files
    frame_invariant_metadata_path = output_directory.joinpath("frame_invariant_metadata.json")
    frame_variant_metadata_path = output_directory.joinpath("frame_variant_metadata.npz")
    ops_path = output_directory.joinpath("ops.json")

    # If raw_mesoscope_frames directory does not exist, either the mesoscope frames are already processed or were not
    # acquired at all. Aborts processing early.
    if not image_directory.exists():
        return

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


def _preprocess_log_directory(raw_data_directory: Path, logger: DataLogger | None = None) -> None:
    """Compresses all .npy (uncompressed) log entries stored in the behavior log directory into one or more .npz
    archives.

    This service function is used during data preprocessing to optimize the size and format used to store all log
    entries. Primarily, this is necessary to facilitate data transfer over the network and log processing on the
    BioHPC server.

    data_directory: The path to the processed session raw_data directory.
    logger: An optional initialized DataLogger instance used to generate the log data. During normal preprocessing, this
        function receives the initialized logger instance used to generate the data from the managing runtime
        function. When this function is used to repeat / resumed failed preprocessing, it initialized its own
        data logger.
    """
    # Unless an initialized DataLogger instance is provided, initializes a DataLogger instance using the default
    # parameters used by the data acquisition pipeline.
    if logger is None:
        logger = DataLogger(output_directory=raw_data_directory, instance_name="behavior", exist_ok=True)

    # Resolves the path to the log directory, using either the input or initialized logger class.
    log_directory = logger.output_directory

    # Searches for compressed and uncompressed files inside the log directory
    compressed_files: list[Path] = [file for file in log_directory.glob("*.npz")]
    uncompressed_files: list[Path] = [file for file in log_directory.glob("*.npy")]

    # If there are no uncompressed files, ends the runtime early
    if len(uncompressed_files) < 0:
        return

    # If the input directory contains .npy (uncompressed) log entries and no compressed log entries, compresses all log
    # entries in the directory
    if len(compressed_files) == 0 and len(uncompressed_files) > 0:
        logger.compress_logs(
            remove_sources=True, memory_mapping=False, verbose=True, compress=True, verify_integrity=True
        )

    # If both compressed and uncompressed log files existing in the same directory, aborts with an error
    elif len(compressed_files) > 0 and len(uncompressed_files) > 0:
        message = (
            "The input log directory contains both compressed and uncompressed log files. Since compression overwrites "
            "the .npz archive with the processed data, it is unsafe to proceed with log compression in automated mode."
            "Manually back up the existing .npz files, remove them from the log directory and call the processing "
            "method again."
        )
        console.error(message, error=RuntimeError)


def preprocess_session_directory(
    raw_data_directory: Path, mesoscope_root_path: Path, logger: DataLogger | None = None
) -> None:
    _preprocess_log_directory(raw_data_directory=raw_data_directory, logger=logger)
    _preprocess_video_names(raw_data_directory=raw_data_directory)
    _pull_mesoscope_data(
        raw_data_directory=raw_data_directory,
        mesoscope_root_directory=mesoscope_root_path,
        num_threads=30,
        remove_sources=True,
        verify_transfer_integrity=True,
    )
    _preprocess_mesoscope_directory(
        raw_data_directory=raw_data_directory,
        num_processes=30,
        remove_sources=True,
        verify_integrity=True,
        batch_size=1,
    )


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
    for candidate in deletion_candidates:
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
    for candidate in deletion_candidates:
        _delete_directory(directory_path=candidate)
