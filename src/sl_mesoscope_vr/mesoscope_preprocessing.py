"""This module provides the methods used to preprocess mesoscope data after acquisition. The primary purpose of this
preprocessing is to prepare the data for storage and further processing in the Sun lab data cluster.
"""

from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

from numpy.typing import NDArray
from tqdm import tqdm
import numpy as np
import tifffile
import json
from ataraxis_base_utilities import console
import matplotlib.pyplot as plt
from suite2p.io.binary import BinaryFile
from typing import Any
import difflib
from datetime import datetime
from contextlib import nullcontext

# from suite2p import registration_wrapper


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
    with tifffile.TiffFile(str(file)) as tif:
        # Gets number of pages (frames) from tiff header
        n_frames = len(tif.pages)

        # Considers all files with more than one page and a 2-dimensional (monochrome) image as a stack. For these
        # stacks, returns the discovered stack size (number of frames).
        if n_frames > 1 and len(tif.pages[0].shape) == 2:
            return n_frames
        # Otherwise, returns 0 to indicate that the file is not a stack.
        return 0


def _load_stack_data(file: Path) -> tuple[NDArray[np.int16], dict[str, Any]]:
    """Loads the target TIFF stack into memory via tifffile and extracts the metadata associated with each frame in the
    stack.

    This function is used to prepare tiff stacks acquired by the mesoscope for compression. It loads the stack data into
    memory and extracts, parses and stores the frame-variant metadata for each loaded frame as a dictionary of numpy
    arrays. The loaded metadata is formatted with sensible numpy datatypes to minimize memory usage.

    Notes:
        This function only works with monochrome TIFF stacks generated by the mesoscope. It expects each TIFF file to
        be a stack of 2D frames.

    Args:
        file: The path to the TIFF stack file.

    Raises:
        NotImplementedError: If the input file is not a supported mesoscope TIFF stack, or if the function does not
            support parsing any extracted frame-variant metadata sub-tags.

    Returns:
        A tuple with two elements. The first element is a numpy NDArray with int16 datatype that stores the raw pixel
        data for all frames inside the stack. The second element is a dictionary that contains parsed 'ImageDescription'
        tag data. The dictionary uses sub-tags as keys and numpy arrays as values. Each array aggregates the data for
        all frames loaded from the stack in the same order as the frame data.
    """

    # Extracts the number of pages inside the stack. Also doubles as a verification mechanism that checks if the file
    # is a mesoscope TIFF stack.
    num_pages = _check_stack_size(file)
    if num_pages == 0:
        message = (
            f"Unable to process the requested TIFF file '{file}'. The file is not a supported mesoscope TIFF stack."
        )
        console.error(message=message, error=NotImplementedError)

    with tifffile.TiffFile(file) as tif:
        stack = tif.asarray()

        # Initializes arrays for storing metadata
        frame_nums = np.zeros(num_pages, dtype=np.int32)
        acq_nums = np.zeros(num_pages, dtype=np.int32)
        frame_num_acq = np.zeros(num_pages, dtype=np.int32)
        frame_timestamps = np.zeros(num_pages, dtype=np.float64)
        acq_trigger_timestamps = np.zeros(num_pages, dtype=np.float64)
        next_file_timestamps = np.zeros(num_pages, dtype=np.float64)
        end_of_acq = np.zeros(num_pages, dtype=np.int32)
        end_of_acq_mode = np.zeros(num_pages, dtype=np.int32)
        dc_over_voltage = np.zeros(num_pages, dtype=np.int32)
        epoch_timestamps = np.zeros(num_pages, dtype=np.uint64)

        # Loops over each page in the stack and extracts the metadata associated with each frame
        for i, page in enumerate(tif.pages):
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
                            f"associated with the tiff file {file}. Update the _load_stack_data() with the logic for "
                            f"parsing the data associated with this field."
                        )
                        console.error(message=message, error=NotImplementedError)
                else:
                    message = (
                        f"Unknown field '{key}' found in the frame-variant ScanImage metadata associated with the tiff "
                        f"file {file}. Update the _load_stack_data() with the logic for parsing the data associated "
                        f"with this field."
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

        return stack, metadata_dict


def _fix_mesoscope_frames(mesoscope_directory: Path, chunk_size: int = 5000) -> None:
    """Loads all frames stored inside the target mesoscope_frames directory into memory and re-saves them as a single
    BigTiff hyperstack.

    This function is used to recompress the frames previously saved as single-frame TIFF files into one BigTiff stack.
    This is used to bring the data preprocessed by the early Sub Lab pipeline to the modern format. Specifically,
    initially we split mesoscope stacks into individual frames, but later a decision was made to instead produce a
    BigTiff stack that includes all frames, instead of ~33000 individual TIFF files.

    Notes:
        This function is NOT memory-safe. We have enough memory on the host-computer to load the entire session into
        RAM, but this function will fail on machines with less than ~100 GB of RAM.

        This function generates a new mesoscope_frames.tiff file in the parent directory where mesoscope_frames folder
        was stored.

        This function verifies the integrity of frames after re-encoding and then removes the source directory and all
        TIFF frame files.

    Args:
        mesoscope_directory: The Path to the mesoscope_frames directory containing the individual frame TIFF files.
        chunk_size: The number of frames to load into memory at a time when recompressing the stack.
    """

    # Generates the list of frame files stored in the directory and sorts them in the order of acquisition.
    tiff_files = sorted(mesoscope_directory.glob("*.tif*"), key=lambda x: int(x.stem))

    # Precreates the output BigTiff file path
    output_path = mesoscope_directory.parent / "mesoscope_frames.tiff"

    # Saves the loaded data as lerc-compressed BigTiff:

    # Loads the data in chunks and appends them to the output BigTiff file
    for i in range(0, len(tiff_files), chunk_size):
        chunk_files = tiff_files[i : i + chunk_size]

        # Load chunk
        with ThreadPoolExecutor() as executor:
            frames = list(executor.map(tifffile.imread, chunk_files))
        chunk_data = np.concatenate(frames, axis=0).astype(np.int16)

        # Write chunk
        tifffile.imwrite(
            output_path,
            chunk_data,
            compression="lerc",
            compressionargs={"level": 0.0},
            predictor=True,
            bigtiff=True,  # Enables BigTiff support
            append=i > 0,  # Append after first chunk
        )

    del chunk_data  # Releases memory to free all resources for the verification step

    # A worker function used to verify the integrity of recompressed frames in-parallel
    def verify_frame(args):
        idx, source_file = args
        source_data = tifffile.imread(source_file)
        with tifffile.TiffFile(output_path) as tif:
            compressed_frame = tif.pages[idx].asarray()
        return np.array_equal(compressed_frame, source_data)

    # Verifies each page of the BigTiff file against its source file
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(verify_frame, enumerate(tiff_files)))

    # Ensures all data passes verification before removing sources
    if not all(results):
        message = (
            f"Verification failed for some frames in {output_path} when re-compressing mesoscope frames to BigTiff."
        )
        console.error(message=message, error=RuntimeError)

    # Removes sources if verification passed and also removes the directory
    for file in tiff_files:
        file.unlink()
    mesoscope_directory.rmdir()


def _process_invariant_metadata(file: Path) -> None:
    """Extracts frame-invariant ScanImage metadata from the target tiff file and outputs it as a JSON file in the same
    directory.

    This function only needs to be called for one raw ScanImage TIFF stack in each directory. It extracts the
    ScanImage metadata that is common for all frames across all stacks and outputs it as metadata.json file. This
    function also calls the _generate_ops() function that generates a suite2p ops.json file from the parsed
    metadata.

    Notes:
        This function is primarily designed to preserve the metadata before converting raw TIFF stacks into a
        single hyperstack and compressing it as LERC. It ensures that all original metadata is preserved for
        future referencing.

    Args:
        file: The path to the mesoscope TIFF stack file. This can be any file in the directory as the
            frame-invariant metadata is the same for all stacks.
    """

    # Uses the parent directory of the target tiff file to create the output JSON file
    metadata_json = Path(file.parent).joinpath("metadata.json")

    # Reads the frame-invariant metadata from the first page (frame) of the stack. This metadata is the same across
    # all frames and stacks.
    with tifffile.TiffFile(file) as tiff:
        metadata = tiff.scanimage_metadata
        frame_data = tiff.asarray(key=0)  # Loads the data for the first frame in the stack to generate ops.json

    # Writes the metadata as a JSON file.
    with open(metadata_json, "w") as json_file:
        # noinspection PyTypeChecker
        json.dump(metadata, json_file, indent=4)

    # Also uses extracted metadata to generate the ops.json configuration file for scanImage processing.
    _generate_ops(metadata=metadata, frame_data=frame_data, data_path=file.parent, output_path=file.parent)


def _generate_ops(
    metadata: dict[str, Any],
    frame_data: NDArray[np.int16],
    data_path: Path,
    output_path: Path,
) -> None:
    """Uses frame-invariant ScanImage metadata and static default values to create an ax_ops.json file in the directory
    specified by data_path.

    This function is an implementation of the mesoscope data extraction helper from the suite2p library. The helper
    function has been reworked to work with the metadata parsed by tifffile and reimplemented in Python. It was
    configured to produce identical output to the ops.json files found in Tyche dataset. Primarily, this function
    generates the 'fs', 'dx', 'dy', 'lines', 'nroi', 'nplanes' and 'mesoscan' fields of the 'ops' configuration file.
    These fields are then reused by our dedicated ops-processing class to generate the ops.npy used to control suite2p
    runtimes.

    Notes:
        The generated ax_ops.json file will be saved in the data_path directory.

    Args:
        metadata: A dictionary containing ScanImage metadata extracted from a mesoscope tiff stack file.
        frame_data: A numpy array containing the data for the first frame of the stack.
        data_path: The path to the directory where the output ops.json file will be saved.
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
        roi_centers[i] = si_rois[i]["scanfields"]["centerXY"][::-1]  # Reverse order to match original matlab code
        roi_sizes[i] = si_rois[i]["scanfields"]["sizeXY"][::-1]

    # Transforms ROI coordinates into pixel-units, while maintaining accurate relative positions for each ROI.
    roi_centers -= roi_sizes / 2  # Shifts ROI coordinates to mark the top left corner
    roi_centers -= np.min(roi_centers, axis=0)  # Normalizes ROI coordinates to leftmost/topmost ROI
    # Calculates pixels-per-unit scaling factor from ROI dimensions
    scale_factor = np.median(np.column_stack([roi_heights, roi_widths]) / roi_sizes, axis=0)
    min_positions = roi_centers * scale_factor  # Converts ROI positions to pixel coordinates

    # Calculates total number of rows across all ROIs (rows of pixels acquired while imaging ROIs)
    total_rows = np.sum(roi_heights)

    # Calculates the number of flyback pixels between ROIs. These are the pixels acquired when the galvos are moving
    # between frames.
    n_flyback = (frame_data.shape[0] - total_rows) / max(1, (nrois - 1))

    # Creates an array that stores the start and end row indices for each ROI
    roi_rows = np.zeros((2, nrois))
    # noinspection PyTypeChecker
    temp = np.concatenate([[0], np.cumsum(roi_heights + n_flyback)])
    roi_rows[0] = temp[:-1]  # Starts are all elements except last
    roi_rows[1] = roi_rows[0] + roi_heights  # Ends calculation stays same

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

    # Generates fields to store the path to the directory that stores raw data and the directory where processed
    # (registered) frames will be moved to.
    data["data_path"] = [str(data_path)]
    data["save_path0"] = str(output_path)

    # Saves the generated config as JSON file (ops.json)
    json_path = data_path.joinpath("ax_ops.json")
    with open(json_path, "w") as f:
        # noinspection PyTypeChecker
        json.dump(data, f)


def _verify_frame(args):
    """A worker function used to verify the integrity of recompressed frames in-parallel.

    This is used during mesoscope frame preprocessing to ensure it is safe to delete recompressed source files.
    """
    idx, (source_file, output_tiff) = args
    source_data = tifffile.imread(source_file)
    with tifffile.TiffFile(output_tiff) as tif:
        compressed_frame = tif.pages[idx].asarray()
    return np.array_equal(compressed_frame, source_data)


def process_mesoscope_directory(
    image_directory: Path, num_processes: int, remove_sources: bool = False, batch: bool = False, chunk_size: int = 20
) -> None:
    """Loops over all multi-frame TIFF stacks in the input directory and recompresses them using LERC scheme.

    This function is used as a preprocessing step for mesoscope-acquired data that optimizes the size of raw images for
    long-term storage and streaming over the network. To do so, each stack is re-encoded using LERC scheme,
    which achieves ~70% compression ratio, compared to the original frame stacks obtained from the mesoscope.

    Notes:
        This function is specifically calibrated to work with TIFF stacks produced by the scanimage matlab software.
        Critically, these stacks are named using '__' to separate session and stack number from the rest of the
        file name, and the stack number is always found last, e.g.: 'Tyche-A7_2022_01_25_1__00001_00067.tif'. If the
        input TIFF files do not follow this naming convention, the function will not work as expected.

        This function assumes that scanimage buffers frames until the stack_size number of frames is available and then
        saves the frames as a TIFF stack. Therefore, it assumes that the directory contains at most one non-full stack.
        The function uses this assumption when assigning unique frame IDs to extracted frames.

        To optimize runtime efficiency, this function employs multiple processes to work with multiple TIFF at the
        same time. It uses the stack number and stack size as a heuristic to determine which IDs to assign to each
        extracted frame while processing stacks in-parallel to avoid collisions.

    Args:
        image_directory: The directory containing the multi-frame TIFF stacks.
        num_processes: The maximum number of processes to use while processing the directory.
        remove_sources: Determines whether to remove the original TIFF files after they have been processed.
        batch: Determines whether the function is called as part of batch-processing multiple directories. This is used
            to optimize progress reporting to avoid cluttering the terminal.
    """
    # Precreates the paths to the output files
    output_tiff = image_directory / "mesoscope_frames.tiff"
    metadata_file = image_directory / "frame_metadata.npz"

    # Precreates the dictionary to store frame-variant metadata extracted from all TIFF frames before they are
    # compressed into BigTiff.
    all_metadata = defaultdict(list)

    # Finds all TIFF files in the input directory (non-recursive).
    tiff_files = list(image_directory.glob("*.tif")) + list(image_directory.glob("*.tiff"))

    # Uses chunking to prevent out-of-memory errors
    with (
        tqdm(range(0, len(tiff_files), chunk_size), desc="Processing TIFF stacks", unit="chunks")
        if not batch
        else nullcontext(range(0, len(tiff_files), chunk_size))
    ) as pbar:
        for i in pbar:
            # Determines the stacks for each chunk
            chunk = tiff_files[i : i + chunk_size]

            # Loads all TIFF stacks from the current chunk pool into memory. Also leads frame-variant metadata for all
            # frames in processed stacks
            with ThreadPoolExecutor(max_workers=num_processes) as executor:
                chunk_results = list(executor.map(_load_stack_data, chunk))

            # Concatenates the frames from all stacks and writes appends them to the end of the BigTiff output file
            chunk_frames = np.concatenate([result[0] for result in chunk_results], axis=0).astype(np.int16)
            tifffile.imwrite(
                output_tiff,
                chunk_frames,
                compression="lerc",
                compressionargs={"level": 0.0},
                predictor=True,
                bigtiff=True,
                append=i > 0,
            )

            # Collects metadata from all chunks into the unified metadata_dictionary as runtime progresses
            for result in chunk_results:
                for key, value in result[1].items():
                    all_metadata[key].append(value)

            pbar.update(1)

        # Removes leftover chunk data once the BigTiff is created to conserve memory
        del chunk_frames

        # Saves concatenated metadata as compressed numpy archive
        metadata_dict = {k: np.concatenate(v) for k, v in all_metadata.items()}
        np.savez(metadata_file, **metadata_dict)

        # Verifies each page of the BigTiff file against its source file
        verify_iter = ((i, (f, output_tiff)) for i, f in enumerate(tiff_files))
        with (
            tqdm(verify_iter, total=len(tiff_files), desc="Verifying frames") if not batch else nullcontext(verify_iter)
        ) as iter_with_paths:
            with ProcessPoolExecutor(max_workers=num_processes) as executor:
                verification = executor.map(_verify_frame, iter_with_paths)

        # Ensures all data passes verification before removing sources
        if not all(verification):
            message = (
                f"Verification failed for some frames in {output_tiff} when re-compressing mesoscope frames to BigTiff."
            )
            console.error(message=message, error=RuntimeError)

        # Removes compressed sources
        if remove_sources:
            for file in tiff_files:
                file.unlink()


def compare_ops_files(ops_1_path: Path, ops_2_path: Path) -> None:
    """Prints the difference between the two input 'ops' JSON files.

    This function is primarily used to debug our metadata extraction pipeline to ensure that the metadata extraction
    produces the same ops.json as the helper matlab script provided by suite2p authors. It eiter prints the difference
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


def compare_mesoscope_frames(
    tiff_path: Path, bin_path: Path, ops_path: Path, tiff_index: int, plane_index: int, render_dpi: int
) -> None:
    """Generates a side-by-side plot of the raw mesoscope plane and the registered mesoscope plane data.

    This function allows comparing raw and registered mesoscope frames. In addition to extracting and showing both
    planes side-by-side, it also generates a plot of difference between the two image pixels and plots it in-line with
    the visual data.

    Notes:
        This function assumes that the mesoscope images multiple ROIs (rectangles) as different planes. It also assumes
        that images of each plane are stacked into a single 'frame' tiff file and that multiple 'frames' are
        concatenated into a single tiff 'stack' during imaging.

        At this time, this function does not support saving the generated images to disk. It is designed for quick
        data inspection by a human researcher.

    Args:
        tiff_path: The path to the raw stack of mesoscope frames acquired by the mesoscope. Each frame can have one or
            more planes (ROIs).
        bin_path: The path to the binary file containing the registered mesoscope plane data.
        ops_path: The path to the ops.json file generated by suite2p helpers or sl_mesoscope helpers. This file is used
            to get the indices of frame rows occupied by each plane.
        tiff_index: The index of the specific tiff file within the input tiff stack to process. This specifies the
            frame to process and is relative to each stack with index 0 being the first frame in the stack.
        plane_index: The index of the specific section within the registered data.bin file to process. This specifies
            the plane (frame) to process and is relative to each bin file with index 0 being the first plane in the
            bin file. This index assumes that the binary file only stores the data for a single plane.
        render_dpi: The resolution at which to render the comparison figures. Since mesoscope frames are fairly large,
            it is beneficial to use larger DPIs to render comparison figures.
    """
    # Reads the specified tiff frame (page) into RAM.
    with tifffile.TiffFile(tiff_path) as tif:
        raw_frame = tif.asarray(key=tiff_index)

    # Uses ops.json to determine the indices for the rows occupied by the targeted plane
    with open(ops_path, "r") as file:
        plane_data = json.load(file)
        lines = plane_data["lines"]

    # Computes the dimensions of the plane using 'lines' as height and the width of the original frame tiff.
    width = raw_frame.shape[1]
    height = len(lines[plane_index])

    raw_plane = raw_frame[lines[plane_index]]  # Extracts the plane data from the raw frame array

    # Extracts the registered plane data for the matching frame
    registered_plane = BinaryFile(Lx=width, Ly=height, filename=str(bin_path))[plane_index]

    # Computes the difference between frames
    difference = raw_plane - registered_plane

    # Applies rendering dpi
    plt.rcParams["figure.dpi"] = render_dpi

    # Creates a figure with three subplots side by side
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6), dpi=render_dpi)

    # Plots raw frame
    ax1.imshow(raw_plane, cmap="gray")
    ax1.set_title("Raw Frame")

    # Plots registered frame
    ax2.imshow(registered_plane, cmap="gray")
    ax2.set_title("Registered Frame")

    # Plots difference
    # Uses 'bwr' colormap where blue is negative, white is zero, red is positive
    im3 = ax3.imshow(difference, cmap="bwr")
    ax3.set_title("Difference (Raw - Registered)")
    plt.colorbar(im3, ax=ax3)

    # Adjusts layout to prevent overlap
    plt.tight_layout()

    # Shows the plot
    plt.show()


if __name__ == "__main__":
    in_path = Path("/home/cybermouse/Desktop/raw/Tyche-F2/2023_02_28/1")
    process_mesoscope_directory(image_directory=in_path, num_processes=70, remove_sources=False, batch=False)

    ops1 = Path("/media/cybermouse/SciDataLin/raw/Tyche-F2/2023_02_27/1/ops.json")
    ops2 = Path("/media/cybermouse/SciDataLin/raw/Tyche-F2/2023_02_27/1/ops2.json")
    # _process_metadata(in_path)
    # compare_ops_files(ops1, ops2)
    # stack_data, stack_metadata = _load_stack_data(in_path)
    # print(stack_metadata)
