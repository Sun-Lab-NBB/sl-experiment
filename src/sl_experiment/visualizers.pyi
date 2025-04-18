import numpy as np
from _typeshed import Incomplete
from numpy.typing import NDArray as NDArray
from ataraxis_time import PrecisionTimer
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.figure import Figure
from ataraxis_data_structures import SharedMemoryArray

_fontdict_axis_label: Incomplete
_fontdict_title: Incomplete
_fontdict_legend: Incomplete
_line_style_dict: Incomplete
_palette_dict: Incomplete

def _plt_palette(color: str) -> tuple[float, float, float]:
    """Converts colloquial color names to pyplot RGB color codes.

    The provided colors are not perfectly colorblind-friendly. They should be used with different 'line style' formats
    to improve readability in monochrome spectrum. The codes generated by this function should be passed to 'color'
    argument of the pyplot module.

    Args:
        color: Colloquial name of the color to be retrieved. Available options are: 'green', 'blue', 'red', 'yellow',
            'purple', 'orange', 'pink', 'black', 'white', 'gray'.

    Returns:
        A list of R, G, and B values for the requested color.

    Raises:
        KeyError: If the provided color is not recognized.
    """

def _plt_line_styles(line_style: str) -> str:
    """Converts colloquial line style names to pyplot's 'lifestyle' string-codes.

    Args:
        line_style: Colloquial name for the line style to be used. Options are 'solid', 'dashed', 'dotdashed' and
            'dotted'.

    Returns:
        The string-code for the requested line style.

    Raises:
        KeyError: If the provided line style is not recognized.
    """

class BehaviorVisualizer:
    """Visualizes lick, valve, and running speed data in real time.

    This class is used to visualize the key behavioral metrics collected from animals performing experiment or training
    sessions in the Mesoscope-VR system. Note, the class is statically configured to generate the plots for all
    supported metrics, even if some of them are not used during a particular session.

    Notes:
        This class is designed to run in the main thread of the runtime context. To update the visualized data, ensure
        that the 'update' class method is called repeatedly during runtime.

    Args:
        lick_tracker: The SharedMemoryArray instance exposed by the LickInterface class that communicates the number of
            licks recorded by the class since runtime onset.
        valve_tracker: The SharedMemoryArray instance exposed by the ValveInterface class that communicates the number
            of times the valve has been opened since runtime onset.
        distance_tracker: The SharedMemoryArray instance exposed by the EncoderInterface class that communicates the
            total distance traveled by the animal since runtime onset, in centimeters.

    Attributes:
        _time_window: Specifies the time window, in seconds, to visualize during runtime. Currently, this is statically
            set to 12 seconds.
        _time_step: Specifies the interval, in milliseconds, at which to update the visualization plots. Currently, this
            is statically set to 30 milliseconds, which gives a good balance between update smoothness and rendering
            time.
        _update_timer: The PrecisionTimer instance used to ensure that the figure is updated once every _time_step
            milliseconds.
        _lick_tracker: Stores the lick_tracker SharedMemoryArray.
        _valve_tracker: Stores the valve_tracker SharedMemoryArray.
        _distance_tracker: Stores the distance_tracker SharedMemoryArray.
        _timestamps: A numpy array that stores the timestamps of the displayed data during visualization runtime. The
            timestamps are generated at class initialization and are kept constant during runtime.
        _lick_data: A numpy array that stores the data used to generate the lick sensor state plot.
        _valve_data: A numpy array that stores the data used to generate the solenoid valve state plot.
        _speed_data: A numpy array that stores the data used to generate the running speed plot.
        _previous_valve_count: Stores the total number of valve pulses sampled during the previous update cycle.
        _previous_lick_count: Stores the total number of licks sampled during the previous update cycle.
        _previous_distance: Stores the total distance traveled by the animal sampled during the previous update cycle.
        _speed_timer: Stores the PrecisionTimer instance used to convert traveled distance into running speed.
        _lick_line: Stores the line class used to plot the lick sensor data.
        _valve_line: Stores the line class used to plot the solenoid valve data.
        _speed_line: Stores the line class used to plot the average running speed data.
        _figure: Stores the matplotlib figure instance used to display the plots.
        _lick_axis: The axis object used to plot the lick sensor data during visualization runtime.
        _valve_axis: The axis object used to plot the solenoid valve data during visualization runtime.
        _speed_axis: The axis object used to plot the average running speed data during visualization runtime.
        _speed_threshold_line: Stores the horizontal line class used to plot the running speed threshold used during
            training sessions.
        _duration_threshold_line: Stores the horizontal line class used to plot the running epoch duration used during
            training sessions.
        _running_speed: Stores the current running speed of the animal. Somewhat confusingly, since we already compute
            the average running speed of the animal via the visualizer, it is easier to retrieve and use it from the
            main training runtime. This value is used to share the current running speed with the training runtime.
        _once: This flag is sued to limit certain visualizer operations to only be called once during runtime.
        _speed_threshold_text: Stores the text object used to display the speed threshold value to the user.
        _duration_threshold_text: Stores the text object used to display the running epoch duration value to the user.
    """

    _time_window: int
    _time_step: int
    _update_timer: Incomplete
    _speed_timer: PrecisionTimer
    _lick_tracker: SharedMemoryArray
    _valve_tracker: SharedMemoryArray
    _distance_tracker: SharedMemoryArray
    _timestamps: NDArray[np.float32]
    _lick_data: NDArray[np.uint8]
    _valve_data: NDArray[np.uint8]
    _speed_data: NDArray[np.float64]
    _previous_valve_count: np.float64
    _previous_lick_count: np.uint64
    _previous_distance: np.float64
    _running_speed: np.float64
    _lick_line: Line2D
    _valve_line: Line2D
    _speed_line: Line2D
    _figure: Figure
    _lick_axis: Axes
    _valve_axis: Axes
    _speed_axis: Axes
    _speed_threshold_line: Line2D
    _duration_threshold_line: Line2D
    _once: bool
    _speed_threshold_text: Incomplete
    _duration_threshold_text: Incomplete
    def __init__(
        self, lick_tracker: SharedMemoryArray, valve_tracker: SharedMemoryArray, distance_tracker: SharedMemoryArray
    ) -> None: ...
    def __del__(self) -> None:
        """Ensures all resources are released when the figure object is garbage-collected."""
    def update(self) -> None:
        """Updates the figure managed by the class to display new data.

        This method discards the oldest datapoint in the plot memory and instead samples a new datapoint. It also shifts
        all datapoints one timestamp to the left. When the method is called repeatedly, this makes the plot lines
        naturally flow from the right (now) to the left (12 seconds in the past), accurately displaying the visualized
        data history.

        Notes:
            The method has an internal update frequency limiter. Therefore, to achieve optimal performance, call this
            method as frequently as possible and rely on the internal limiter to force the specific update frequency.
        """
    def update_speed_thresholds(
        self, speed_threshold: float | np.float64, duration_threshold: float | np.float64
    ) -> None:
        """Updates the running speed and duration threshold lines to use the input anchor values.

        This positions the threshold lines in the running speed plot to indicate the cut-offs for the running speed and
        running epoch duration that elicit water rewards. This is used during run training to visualize the thresholds
        the animal needs to meet to receive water rewards.

        Args:
            speed_threshold: The speed, in centimeter per second, the animal needs to maintain to get water rewards.
            duration_threshold: The duration, in milliseconds, the animal has to maintain the above-threshold speed to
                get water rewards.
        """
    def close(self) -> None:
        """Closes the visualized figure and cleans up the resources used by the class during runtime."""
    def _sample_data(self) -> None:
        """Samples new data from tracker SharedMemoryArray instances and update the class memory."""
    @property
    def running_speed(self) -> np.float64:
        """Returns the current running speed of the animal, calculated over the window of the last 100 milliseconds."""
