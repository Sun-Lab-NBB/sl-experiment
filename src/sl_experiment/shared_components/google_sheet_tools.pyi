from pathlib import Path

from _typeshed import Incomplete
from sl_shared_assets import SurgeryData

_supported_date_formats: set[str]
_required_surgery_headers: set[str]
_required_water_restriction_headers: set[str]

def _convert_date_time_to_timestamp(date: str, time: str) -> int:
    """Converts the input date and time strings into the UTC timestamp.

    This function is used to convert date and time strings parsed from the Google Sheet into the microseconds since
    UTC epoch onset, which is the primary time format used by all other library components.

    Args:
        date: The date string in the format "%m-%d-%y" or "%m-%d-%Y".
        time: The time string in the format "%H:%M".

    Returns:
        The number of microseconds elapsed since UTC epoch onset as an integer.

    Raises:
        ValueError: If date or time are not non-empty strings. If the date or time format does not match any of the
            supported formats.
    """

def _extract_coordinate_value(substring: str) -> float:
    """Extracts the numeric value from the input stereotactic coordinate substring.

    This worker function is used to extract the numeric value for each implant and injection coordinate parsed from the
    Google Sheet data.

    Args:
        substring: The stereotactic coordinate substring that contains the numeric value to be extracted.

    Returns:
        The extracted numeric value, formatted as a float.

    Raises:
        ValueError: If the input substring does not contain a numerical value for the anatomical coordinate.
    """

def _parse_stereotactic_coordinates(coordinate_string: str) -> tuple[float, float, float]:
    """Parses the AP, ML, and DV stereotactic coordinates from the input coordinate string, extracted from the Google
    Sheet data.

    This method is used when generating ImplantData and InjectionData classes to process the coordinates for each
    implant and injection.

    Notes:
        This method expects the coordinates to be stored as a string formatted as: "-1.8 AP, 2 ML, .25 DV".

    Args:
        coordinate_string: The input string containing the stereotactic coordinates, formatted as described above.

    Returns:
        The tuple of 3 floats, each storing the numeric value of the coordinates in the following order: AP, ML, DV.
    """

def _convert_index_to_column_letter(index: int) -> str:
    """Converts a 0-based column index to an Excel-style (Google Sheet) column letter (A, B, C, ... Z, AA, AB, ...).

    This is used when parsing the available headers from the Google Sheet to generate the initial column-to-header
    mapping dictionary.

     Args:
        index: The 0-based column index to be converted.

    Returns:
        The Excel-style column letter corresponding to the input index.
    """

def _replace_empty_values(row_data: list[str]) -> list[str | None]:
    """Replaces empty cells and cells containing 'n/a', '--' or '---' inside the input row_data list with None.

    This is used when retrieving animal data to filter out empty cells and values.

    Args:
        row_data: The list of cell values from a single Google Sheet row.

    Returns:
        The filtered version of the input list.
    """

class SurgerySheet:
    """Encapsulates the access to the target Google Sheet that contains shared lab surgery logs.

    This class uses Google Sheets API to connect to and extract the data stored in the surgery log Google Sheet file.
    It functions as the central access point used to extract surgery data for each animal and project combination and
    save it as a .yaml file alongside other recorded training or experiment data.

    The class is explicitly designed to work with the data of a single animal, which matches the case of how the class
    is used during data acquisition in the lab. It carries out all necessary checks at instantiation to ensure correct
    operation of all methods. Make sure the class is instantiated early in the session initialization hierarchy to abort
    the runtime if necessary.

    Notes:
        This class is purpose-built to work with the specific surgery log format used in the Sun lab. If the target
        sheet or project tab layout does not conform to expectations, this class will likely not behave as intended.

        Since version 2.0.0 this class is also used to write the Surgery Quality column value as the result of
        running the "window checking" session.

    Args:
        project_name: The name of the project whose data should be parsed by the class instance. It is expected that the
            target sheet stores all Sun Lab projects as individual tabs.
        animal_id: The numeric ID of the animal whose data should be parsed by the class instance. It is expected that
            all animals use numeric IDs (either project-specific or unique across all projects) as \'names\'.
        credentials_path: The path to the JSON file containing the service account credentials for accessing the Google
            Sheet.
        sheet_id: The ID of the Google Sheet containing the surgery data.

    Attributes:
        _project_name: Stores the target project name.
        _animal_id: Stores the target animal ID.
        _sheet_id: Stores the ID of the target Google Sheet.
        _service: The Google Sheets API service instance used to fetch data from the target Google Sheet.
        _headers: A dictionary that uses headers (column names) as keys and Google Sheet column names (A, B, etc.) as
            values. This dictionary stores all user-defined headers used by the target Google Sheet tab.
        _animals: Stores all animal IDs (names) whose data is stored in the target Google Sheet tab.

    Raises:
        ValueError: If the sheet is not formatted correctly or does not contain expected data.
    """

    _project_name: Incomplete
    _animal_id: Incomplete
    _sheet_id: Incomplete
    _service: Incomplete
    _headers: dict[str, str]
    _animals: tuple[str, ...]
    def __init__(self, project_name: str, animal_id: int, credentials_path: Path, sheet_id: str) -> None: ...
    def __del__(self) -> None:
        """Terminates the Google Sheets API service when the class is garbage-collected."""
    def extract_animal_data(self) -> SurgeryData:
        """Extracts the surgery data for the target animal and returns it as a SurgeryData object.

        This method is used by all acquisition systems at the beginning of each data acquisition session to extract and
        cache the surgery intervention data of the processed animal.

        Returns:
            A fully configured SurgeryData instance that stores the extracted data.
        """
    def update_surgery_quality(self, quality: int) -> None:
        """Updates the surgery quality value for the specified animal.

        This method is used to write an integer value to the \'Surgery Quality\' column for the specified animal.
        The value represents the quality assessment of the surgical intervention performed on the animal, typically
        made after the first pre-training imaging session ("window checking" session).

        Args:
            quality: The integer value representing the surgery quality to be written. The value reflects the quality
                of the animal for scientific data acquisition: 0 means unusable, 1 means usable for testing (but not
                publications), 2 means publication-grade quality.
        """
    def _get_column_id(self, column_name: str) -> str | None:
        """Returns the Google Sheet column ID (letter) for the given column name.

        This method assumes that the header name comes from the data extracted from the header row of the processed
        sheet. The method is used during animal-specific data parsing to retrieve data from specific columns.

        Args:
            column_name: The name of the column as it appears in the header row.

        Returns:
            The column ID (e.g., "A", "B", "C") corresponding to the column name. If the target column header does not
            exist, the method returns None to indicate the header is not available.
        """

class WaterSheet:
    """Encapsulates the access to the target Google Sheet that contains project water-restriction data.

    This class uses Google Sheets API to connect to and update the data stored in the water restriction log Google Sheet
    file. It functions as the central access point used to update the water restriction data for each animal after
    training and experiment sessions. Primarily, this is used as a convenience feature that allows experimenters to
    synchronize runtime data with the Google Sheet tracker instead of entering it manually.

    The class is explicitly designed to work with the data of a single data acquisition session and animal, which
    matches the case of how the class is used during data acquisition in the lab. It carries out all necessary checks at
    instantiation to ensure correct operation of all methods. Make sure the class is instantiated early in the session
    initialization hierarchy to abort the runtime if necessary.

    Notes:
        This class is purpose-built to work with the specific water restriction log format used in the Sun lab. If the
        target sheet layout does not conform to expectations, this class will likely not perform as intended.

        In contrast to the surgery log, the water restriction log does not store project-specific information. While
        the general assumption is that each project uses a unique water restriction log file, the system also supports
        experimenters that use unique IDs for all mice, across all projects.

    Args:
        animal_id: The ID of the animal whose data will be written by this class instance.
        session_date: The date of the session whose data will be written by this class instance. Date is used as the
            'id' of each session in the format YYYY-MM-DD-HH-MM-SS-US, so setting this to session name (id) is the
            expected behavior.
        credentials_path: The path to the JSON file containing the service account credentials for accessing the Google
            Sheet.
        sheet_id: The ID of the Google Sheet containing the water restriction data for the target project.


    Attributes:
        _sheet_id: Stores the ID of the target Google Sheet.
        _service: The Google Sheets API service instance used to write data to the target Google Sheet.

        _animals: Stores all animal IDs (names) whose data is stored in the target Google Sheet.
        _headers: A dictionary that uses headers (column names) as keys and Google Sheet column names (A, B, etc.) as
            values. This dictionary stores all user-defined headers used by the target Google Sheet tab (animal tab).
        _sheet_id_numeric: The numeric ID of the tab that stores the data for the managed animal. This is used to write
         the data to the target animal's tab.
         _current_time: Stores the time (HH:MM) of the session.
         _session_row_index: Stores the index of the Google Sheet row where to write the managed session's data.

    Raises:
        ValueError: If the sheet is not formatted correctly or does not contain expected data.
    """

    _animal_id: Incomplete
    _sheet_id: Incomplete
    _service: Incomplete
    _sheet_id_numeric: Incomplete
    _animals: tuple[str, ...]
    _headers: dict[str, str]
    _current_time: Incomplete
    _session_row_index: Incomplete
    def __init__(self, animal_id: int, session_date: str, credentials_path: Path, sheet_id: str) -> None: ...
    def __del__(self) -> None:
        """Terminates the Google Sheets API service when the class is garbage-collected."""
    def update_water_log(self, mouse_weight: float, water_ml: float, experimenter_id: str, session_type: str) -> None:
        """Updates the water restriction log for the managed animal's training or experiment data.

        This method is used at the end of each BehaviorTraining or MesoscopeExperiment runtime to update the water
        restriction log with the runtime data. Primarily, this is used to keep a record of behavior interventions and to
        streamline experimenter experience by automatically synchronizing the Google Sheet log with the data logged
        during runtime.

        Notes:
            For this method to work as intended, the target water restriction log tab must be pre-filled with dates
            at least up to today's data. The method searches the 'date' column for today's date and uses it to determine
            which row of the table to update with data.

        Args:
            mouse_weight: The weight of the mouse, in grams, at the beginning of the training or experiment session.
            water_ml: The combined volume of water, in milliliters, given to the animal automatically (during runtime)
                and manually (by the experimenter, after runtime).
            experimenter_id: The ID of the experimenter running the training or experiment session.
            session_type: The type of the training or experiment session. This is written to the 'behavior'
                column to describe the type of activity performed by the animal during runtime.
        """
    def _find_date_row(self, target_date: str) -> int:
        """Finds the row index inside the manged water restriction log file containing the target date.

        This is used when updating the log with new data to determine which row to write the data to.

        Args:
            target_date: The date to find in 'mm/dd/yyyy' format.

        Returns:
            The row index (1-based), containing the target date.

        Raises:
            ValueError: If the target data is not found inside the managed Google Sheet file.
        """
    def _write_value(self, column_name: str, row_index: int, value: int | float | str) -> None:
        """Writes the input value to the specific cell based on column name and row index.

        This is the primary method used to write new values to the managed water restriction log Google Sheet.

        Args:
            column_name: The name of the column to write to.
            row_index: The row index (1-based) to write to.
            value: The value to write.
        """
