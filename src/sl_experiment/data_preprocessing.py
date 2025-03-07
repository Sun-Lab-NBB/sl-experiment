"""This module provides the methods used to preprocess experimental data after acquisition. The primary purpose of this
preprocessing is to prepare the data for storage and further processing in the Sun lab data cluster.
"""

import json
from typing import Any
import difflib
from pathlib import Path
from datetime import datetime
from functools import partial
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from tqdm import tqdm
import numpy as np
import tifffile
from numpy.typing import NDArray
from ataraxis_base_utilities import console
from ataraxis_video_system import extract_logged_video_system_data
from ataraxis_communication_interface import extract_logged_hardware_module_data
from .module_interfaces import (
    TTLInterface,
    LickInterface,
    BreakInterface,
    ValveInterface,
    ScreenInterface,
    TorqueInterface,
    EncoderInterface,
)
import polars as pl


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
    tiff_path: Path, first_frame_number: int, output_dir: Path, remove_sources: bool, verify_integrity: bool
) -> dict[str, Any]:
    """Reads a TIFF stack, extracts its frame-variant ScanImage data, and saves it as a LERC-compressed stacked TIFF
    file.

    This is a worker function called by the process_mesoscope_directory in-parallel for each stack inside each
    processed directory. It re-compresses the input TIFF stack using LERC-compression and extracts the frame-variant
    ScanImage metadata for each frame inside the stack. Optionally, the function can be configured to verify data
    integrity after compression and to remove original TIFF stacks after processing.

    Notes:
        This function can reserve up to double the processed stack size of RAM bytes to hold the data in memory. If the
        host-computer does not have enough RAM, reduce the number of concurrent processes or disable verification.

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
        remove_sources: Determines whether to remove original TIFF stacks after processing.
        verify_integrity: Determines whether to verify the integrity of compressed data against the source data.
            The conversion does not alter the source data, so it is usually safe to disable this option, as the chance
            of compromising the data is negligible. Note, enabling this function doubles the RAM usage for each worker
            process.
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

        # Loads stack data
        original_stack = stack.asarray()  # Reads the data as a numpy array into RAM

        # Computes the starting and ending frame number
        start_frame = first_frame_number  # This is precomputed to be correct, no adjustment needed
        end_frame = first_frame_number + stack_size - 1  # Ending frame number is length - 1 + start

        # Creates the output path for the compressed stack. Uses 6-digit padding for frame numbering
        output_path = output_dir.joinpath(f"mesoscope_{str(start_frame).zfill(6)}_{str(end_frame).zfill(6)}.tiff")

        # Compresses and writes the data to the output path generated above
        tifffile.imwrite(
            output_path,
            original_stack,
            compression="lerc",
            compressionargs={"level": 0.0},  # Lossless compression
            predictor=True,
        )

    # Verifies the integrity of the compressed stack.
    if verify_integrity:
        compressed_stack = tifffile.imread(output_path)
        if not np.array_equal(compressed_stack, original_stack):
            message = f"Compressed stack {output_path} does not match the original stack in {tiff_path}."
            console.error(message=message, error=RuntimeError)

    # Removes the original file if requested
    if remove_sources:
        tiff_path.unlink()

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


def process_invariant_metadata(file: Path, ops_path: Path, metadata_path: Path) -> None:
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


def process_mesoscope_directory(
    image_directory: Path,
    output_directory: Path,
    ops_path: Path,
    frame_invariant_metadata_path: Path,
    frame_variant_metadata_path: Path,
    num_processes: int,
    remove_sources: bool = False,
    batch: bool = False,
    verify_integrity: bool = True,
) -> None:
    """Loops over all multi-frame TIFF stacks in the input directory, recompresses them using Limited Error Raster
    Compression (LERC) scheme, and extracts ScanImage metadata.

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
        combine both methods.

    Args:
        image_directory: The directory containing the multi-frame TIFF stacks. Usually, this is the raw_data directory
            of the project-animal-session hierarchy.
        output_directory: The path to the directory where to save processed (compressed) TIFF stacks.
        ops_path: The path to the ops.json file that should be created by this function. This file is used during
            suite2p registration (processing) of the mesoscope data.
        frame_invariant_metadata_path: The path to the metadata.json file that stores frame-invariant metadata. This
            metadata is the same across the stacks and frames of the same session. Currently, this data is not used for
            further processing, but it is preserved in case it is ever necessary in the future.
        frame_variant_metadata_path: The path to the metadata.npz file that stores frame-variant metadata for each frame
            acquired during the same session. Similar to frame-invariant metadata, this file is not use for further
            processing at this time.
        num_processes: The maximum number of processes to use while processing the directory. Each process is used to
            compress a stack of TIFF files in parallel.
        remove_sources: Determines whether to remove the original TIFF files after they have been processed.
        batch: Determines whether the function is called as part of batch-processing multiple directories. This is used
            to optimize progress reporting to avoid cluttering the terminal window.
        verify_integrity: Determines whether to verify the integrity of compressed data against the source data.
            The conversion does not alter the source data, so it is usually safe to disable this option, as the chance
            of compromising the data is negligible. Note, enabling this function doubles the RAM used by each parallel
            worker spawned by this function.
    """

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
    process_invariant_metadata(file=tiff_files[0], ops_path=ops_path, metadata_path=frame_invariant_metadata_path)

    # Uses partial to bind the constant arguments to the processing function
    process_func = partial(
        _process_stack, output_dir=output_directory, remove_sources=remove_sources, verify_integrity=verify_integrity
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
    np.savez(frame_variant_metadata_path, **metadata_dict)


def compare_ops_files(ops_1_path: Path, ops_2_path: Path) -> None:
    """Prints the difference between the two input 'ops' JSON files.

    This function is primarily used to debug our metadata extraction pipeline to ensure that the metadata extraction
    produces the same ops.json as the helper matlab script provided by suite2p authors. It either prints the difference
    between the files to the terminal or a static line informing the user that the files are identical.

    Args:
        ops_1_path: The path to the first 'ops' JSON file.
        ops_2_path: The path to the second 'ops' JSON file.

    """
    # Loads both files into memory
    with open(ops_1_path, "r", encoding="utf-8") as f1:
        data1 = json.load(f1)
    with open(ops_2_path, "r", encoding="utf-8") as f2:
        data2 = json.load(f2)

    # Converts back to JSON with sorted keys, so differences are consistent
    json1 = json.dumps(data1, sort_keys=True, indent=2)
    json2 = json.dumps(data2, sort_keys=True, indent=2)

    # Compares line by line
    diff = difflib.unified_diff(
        json1.splitlines(), json2.splitlines(), fromfile=str(ops_1_path), tofile=str(ops_2_path), lineterm=""
    )

    # Prints the difference
    printed = False
    for line in diff:
        printed = True
        print(line)
    if not printed:
        print("No differences found! The ops JSON content is identical.")


def interpolate_data(
    timestamps: NDArray[np.uint64],
    data: NDArray[np.signedinteger[Any] | np.unsignedinteger[Any] | np.floating[Any]],
    seed_timestamps: NDArray[np.uint64],
    is_discrete: bool,
) -> NDArray[np.signedinteger[Any] | np.unsignedinteger[Any] | np.floating[Any]]:
    """Interpolates data values for the provided seed timestamps.

    This function is primarily used during behavioral data preprocessing to align all behavioral data to the mesoscope
    frame acquisition timestamps. In turn, this aligns behavioral recordings to the brain activity data, simplifying
    future data analysis.

    Notes:
        This function expects seed_timestamps and timestamps arrays to be monotonically increasing.

        Discrete interpolated data will be returned as an array with the same datatype as the input data. Continuous
        interpolated data will always use float_64 datatype.

    Args:
        timestamps: The one-dimensional numpy array that stores the timestamps for source datapoints.
        data: The two-dimensional numpy array that stores the source datapoints.
        seed_timestamps: The one-dimensional numpy array that stores the timestamps for which to interpolate the data
            values.
        is_discrete: A boolean flag that determines whether the data is discrete or continuous.

    Returns:
        A numpy NDArray with the same dimension as the seed_timestamps array that stores the interpolated data values.
    """
    # Discrete data
    if is_discrete:
        # Preallocates the output array
        interpolated_data = np.empty(seed_timestamps.shape, dtype=data.dtype)

        # Handles boundary conditions in bulk using boolean masks. All seed timestamps below the minimum source
        # timestamp are statically set to data[0], and all seed timestamps above the maximum source timestamp are set
        # to data[-1].
        below_min = seed_timestamps < timestamps[0]
        above_max = seed_timestamps > timestamps[-1]
        within_bounds = ~(below_min | above_max)  # The portion of the seed that is within the source timestamp boundary

        # Assigns out-of-bounds values in-bulk
        interpolated_data[below_min] = data[0]
        interpolated_data[above_max] = data[-1]

        # Processes within-boundary timestamps by finding the last known certain value to the left of each seed
        # timestamp and setting each seed timestamp to that value.
        if np.any(within_bounds):
            indices = np.searchsorted(timestamps, seed_timestamps[within_bounds], side="right") - 1
            interpolated_data[within_bounds] = data[indices]

        return interpolated_data

    # Continuous data. Note, due to interpolation, continuous data is always returned using float_64 datatype.
    else:
        return np.interp(seed_timestamps, timestamps, data)


def process_camera_timestamps(log_path: Path, output_path: Path) -> None:
    """Reads the log .npz archive specified by the log_path and extracts the camera frame timestamps
    as a Polars Series saved to the output_path as a Feather file.

    Args:
        log_path: Path to the .npz log archive to be parsed.
        output_path: Path to save the output Polars Series as a Feather file.
    """
    # Extracts timestamp data from log archive
    timestamp_data = extract_logged_video_system_data(log_path)

    # Converts extracted data to Polars series.
    timestamps_series = pl.Series(name="timestamps_us", values=timestamp_data)

    # Saves extracted data using Feather format and 'lz4' compression. Lz4 allows optimizing processing time and
    # file size. These extracted files are temporary and will be removed during later processing steps.
    timestamps_series.to_frame().write_ipc(file=output_path, compression="lz4")


def process_module_data(
    log_path: Path,
    module_type: int,
    module_id: int,
    output_path: Path,
    cm_per_pulse: np.float64 = np.float64(0),
    maximum_break_strength: np.float64 = np.float64(0),
    minimum_break_strength: np.float64 = np.float64(0),
    lick_threshold: int = 0,
    scale_coefficient: np.float64 = np.float64(0),
    nonlinearity_exponent: np.float64 = np.float64(0),
    torque_per_adc_unit: np.float64 = np.float64(0),
    initially_on: bool = False,
) -> None:
    """Extracts and parses the data logged by the hardware module during runtime from the compressed .npz log archive
    and saves the parsed data to the output_path as a Polars DataFrame saved to the Feather file.

    This function uses hardware-module-specific parsing logic for each input module and can only work with module types
    hardcoded into this function. Source code modification will be required to support more module types.

    Notes:
        Most arguments are pre-initialized to nonsensical defaults. It is expected that the caller provides the
        appropriate argument values for the processed module type. Failure to do so may result in unexpected behavior or
        invalid parsing output.

    Args:
        log_path: Path to the .npz log archive to be parsed.
        module_type: The type (family) ID code of the module whose data is processed by this function.
        module_id: The instance ID code of the module whose data is processed by this function.
        output_path: Path to save the output Polars Series or DataFrame as a Feather file.
        cm_per_pulse: Only for Encoder modules. The conversion factor to translate encoder pulses to centimeters.
        maximum_break_strength: Only for Break modules. The maximum torque of the break, in Newton centimeters.
        minimum_break_strength: Only for Break modules. The minimum torque of the break, in Newton centimeters.
        lick_threshold: Only for Lick modules. The threshold for detecting licks from the voltage level recorded by the
            sensor, in ADC units of a 12-bit Analog-to-Digital sensor.
        scale_coefficient: Only for Valve modules. The scaling coefficient of the power law equation used to translate
            water valve open duration into dispersed water volume.
        nonlinearity_exponent: Only for Valve modules. The exponent of the power law equation used to translate
            water valve open duration into dispersed water volume.
        torque_per_adc_unit: Only for Torque modules. The conversion factor used to translate the raw ADC readouts of
            the 12-bit Analog-to-Digital sensor into torque values in Newton centimeters, applied by the animal to the
            wheel.
        initially_on: Only for Screens module. Indicates whether the screens are initially on or off at module interface
            initialization.

    Raises:
        ValueError: If the input module type is not recognized (does not have an associated data parsing method).
    """

    # Reads the log archive and extracts the data generated by the module.
    module_data = extract_logged_hardware_module_data(log_path=log_path, module_type=module_type, module_id=module_id)

    # Determines the appropriate log parsing function to call based on the module type. Unfortunately, unlike camera
    # frame processing, module data is processed differently for each hardware module.

    # Mesoscope Frame TTL
    if module_type == 1:
        # TTLModules are unique, as the parsing function only returns the timestamp array. Currently, this is only used
        # to parse mesoscope frame timestamps.
        extracted_data = TTLInterface.parse_logged_data(log_data=module_data)
        module_series = pl.Series(name="time_us", values=extracted_data, dtype=pl.UInt64)
        module_series.to_frame().write_ipc(file=output_path, compression="lz4")

    # Encoder
    elif module_type == 2:
        extracted_data = EncoderInterface.parse_logged_data(log_data=module_data, cm_per_pulse=cm_per_pulse)
        module_dataframe = pl.DataFrame(
            {
                "time_us": extracted_data[0],
                "traveled_distance_cm": extracted_data[1],
            }
        )
        module_dataframe.write_ipc(file=output_path, compression="lz4")

    # Break
    elif module_type == 3:
        extracted_data = BreakInterface.parse_logged_data(
            log_data=module_data,
            maximum_break_strength=maximum_break_strength,
            minimum_break_strength=minimum_break_strength,
        )
        module_dataframe = pl.DataFrame(
            {
                "time_us": extracted_data[0],
                "break_torque_N_cm": extracted_data[1],
            }
        )
        module_dataframe.write_ipc(file=output_path, compression="lz4")

    # Lick Sensor
    elif module_type == 4:
        extracted_data = LickInterface.parse_logged_data(
            log_data=module_data,
            lick_threshold=lick_threshold,
        )
        module_dataframe = pl.DataFrame(
            {
                "time_us": extracted_data[0],
                "lick_state": extracted_data[1],
            }
        )
        module_dataframe.write_ipc(file=output_path, compression="lz4")

    # Valve Sensor
    elif module_type == 5:
        extracted_data = ValveInterface.parse_logged_data(
            log_data=module_data,
            scale_coefficient=scale_coefficient,
            nonlinearity_exponent=nonlinearity_exponent
        )
        module_dataframe = pl.DataFrame(
            {
                "time_us": extracted_data[0],
                "dispensed_water_volume_uL": extracted_data[1],
            }
        )
        module_dataframe.write_ipc(file=output_path, compression="lz4")

    # Torque Sensor
    elif module_type == 6:
        extracted_data = TorqueInterface.parse_logged_data(
            log_data=module_data,
            torque_per_adc_unit=torque_per_adc_unit,
        )
        module_dataframe = pl.DataFrame(
            {
                "time_us": extracted_data[0],
                "mouse_torque_N_cm": extracted_data[1],
            }
        )
        module_dataframe.write_ipc(file=output_path, compression="lz4")

    # Screen State
    elif module_type == 7:
        extracted_data = ScreenInterface.parse_logged_data(
            log_data=module_data,
            initially_on=initially_on
        )
        module_dataframe = pl.DataFrame(
            {
                "time_us": extracted_data[0],
                "screen_state": extracted_data[1],
            }
        )
        module_dataframe.write_ipc(file=output_path, compression="lz4")

    # if module type is not recognized, raises an error
    else:
        message = f"Unsupported module type: {module_type} encountered when parsing log file {log_path}."
        console.error(message, error=ValueError)
