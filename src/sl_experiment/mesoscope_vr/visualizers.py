"""This module provides the Visualizer class that renders the animal's task performance data in real time during
training and experiment runtimes.
"""

import numpy as np
import matplotlib
from numpy.typing import NDArray

matplotlib.use("QtAgg")  # Uses QT backend for performance and compatibility with Linux

from ataraxis_time import PrecisionTimer
from matplotlib.axes import Axes
from matplotlib.text import Text
from matplotlib.lines import Line2D
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, FixedLocator, FixedFormatter
from ataraxis_base_utilities import console

# Updates plotting dictionaries to preferentially use Arial text style and specific sizes for different text elements
# in plots:
# General parameters and the font size for axes' tick numbers
plt.rcParams.update({"font.family": "Arial", "font.weight": "normal", "xtick.labelsize": 16, "ytick.labelsize": 16})
_fontdict_axis_label = {"family": "Arial", "weight": "normal", "size": 18}  # Axis label fonts
_fontdict_title = {"family": "Arial", "weight": "normal", "size": 20}  # Title fonts
_fontdict_legend = {"family": "Arial", "weight": "normal", "size": 14}  # Legend fonts

# Initializes dictionaries to map colloquial names to specific linestyle and color parameters
_line_style_dict = {"solid": "-", "dashed": "--", "dotdashed": "_.", "dotted": ":"}
_palette_dict = {
    "green": (0.000, 0.639, 0.408),
    "blue": (0.000, 0.525, 0.749),
    "red": (0.769, 0.008, 0.137),
    "yellow": (1.000, 0.827, 0.000),
    "purple": (0.549, 0.000, 0.749),
    "orange": (1.000, 0.502, 0.000),
    "pink": (0.945, 0.569, 0.608),
    "black": (0.000, 0.000, 0.000),
    "white": (1.000, 1.000, 1.000),
    "gray": (0.500, 0.500, 0.500),
}


def _plt_palette(color: str) -> tuple[float, float, float]:
    """Converts colloquial color names to pyplot RGB color codes.

    Args:
        color: The colloquial name of the color to be retrieved. Available options are: 'green', 'blue', 'red',
            'yellow', 'purple', 'orange', 'pink', 'black', 'white', 'gray'.

    Returns:
        A list of R, G, and B values for the requested color.

    Raises:
        KeyError: If the input color name is not recognized.
    """
    try:
        return _palette_dict[color]
    except KeyError:
        message = (
            f"Unexpected color name '{color}' encountered when converting the colloquial color name to RGB array. "
            f"Provide one of the supported color arguments: {', '.join(_palette_dict.keys())}."
        )
        console.error(message=message, error=KeyError)
        # Fallback to appease mypy, should not be reachable
        raise KeyError(message)  # pragma: no cover


def _plt_line_styles(line_style: str) -> str:
    """Converts colloquial line style names to pyplot's 'linestyle' string-codes.

    Args:
        line_style: The colloquial name for the line style to be used. Available options are: 'solid', 'dashed',
            'dotdashed' and 'dotted'.

    Returns:
        The string-code for the requested line style.

    Raises:
        KeyError: If the input line style is not recognized.
    """
    try:
        return str(_line_style_dict[line_style])
    except KeyError:
        message = (
            f"Unexpected line style name '{line_style}' encountered when converting the colloquial line style name to "
            f"the pyplot linestyle string. Provide one of the supported line style arguments: "
            f"{', '.join(_line_style_dict.keys())}."
        )
        console.error(message=message, error=KeyError)
        # Fallback to appease mypy, should not be reachable
        raise KeyError(message)  # pragma: no cover


class BehaviorVisualizer:
    """Visualizes lick, valve, and running speed data in real time.

    Notes:
        This class is designed to run in the main thread of the runtime control process. To update the visualized data,
        call the 'update' class method as part of the runtime cycle method.

        Calling this initializer does not open the visualizer plot window. Call the open() class method to finalize
        the visualizer initialization before starting runtime.

    Attributes:
        _event_tick_true: Stores a NumPy uint8 value of 1 to expedite visualization data processing.
        _event_tick_false: Stores a NumPy uint8 value of 0 to expedite visualization data processing.
        _time_window: Specifies the time window, in seconds, to visualize during runtime.
        _time_step: Specifies the interval, in milliseconds, at which to update the visualization plots.
        _update_timer: The PrecisionTimer instance used to enforce the visualization plot update interval set by the
            _time_step attribute.
        _timestamps: Stores the timestamps of the displayed data during visualization runtime.
        _lick_data: Stores the data used to generate the lick sensor state plot.
        _valve_data: Stores the data used to generate the solenoid valve state plot.
        _speed_data: Stores the data used to generate the running speed plot.
        _lick_event: Determines whether the lick sensor has reported a new lick event since the last visualizer update.
        _valve_event: Determines whether the valve was used to deliver a new reward since the last visualizer update.
        _lick_line: The line for the lick sensor data plot.
        _valve_line: The line for the solenoid valve data plot.
        _speed_line: The line for the average running speed data plot.
        _figure: The figure that displays the plots.
        _lick_axis: The axis for the lick sensor data plot.
        _valve_axis: The axis for the solenoid valve data plot.
        _speed_axis: The axis for the average running speed data plot.
        _speed_threshold_line: The horizontal line that shows the running speed threshold used during training sessions.
        _duration_threshold_line: The vertical line that shows the running epoch duration used during training sessions.
        _running_speed: The current running speed of the animal, in cm / s, averaged over a time-window of 50 ms.
        _once: Limits certain visualizer setup operations to only be called once during runtime.
        _is_open: Tracks whether the visualizer plot has been created.
        _speed_threshold_text: The text object that communicates the speed threshold value to the user.
        _duration_threshold_text: The text object that communicates the running epoch duration value to the user.
    """

    # Pre-initializes NumPy event ticks to slightly reduce cyclic visualizer update speed
    _event_tick_true = np.uint8(1)
    _event_tick_false = np.uint8(0)

    def __init__(
        self,
    ) -> None:
        # Currently, the class is statically configured to visualize the sliding window of 10 seconds updated every 25
        # ms.
        self._time_window: int = 10
        self._time_step: int = 25
        self._update_timer = PrecisionTimer("ms")

        # Pre-creates the structures used to store the displayed data during visualization runtime
        self._timestamps: NDArray[np.float32] = np.arange(
            start=0 - self._time_window, stop=self._time_step / 1000, step=self._time_step / 1000, dtype=np.float32
        )
        self._lick_data: NDArray[np.uint8] = np.zeros_like(a=self._timestamps, dtype=np.uint8)
        self._valve_data: NDArray[np.uint8] = np.zeros_like(a=self._timestamps, dtype=np.uint8)
        self._speed_data: NDArray[np.float64] = np.zeros_like(a=self._timestamps, dtype=np.float64)
        self._valve_event: bool = False
        self._lick_event: bool = False
        self._running_speed: np.float64 = np.float64(0)

        # Line objects (to be created during open())
        self._lick_line: Line2D | None = None
        self._valve_line: Line2D | None = None
        self._speed_line: Line2D | None = None

        # Figure objects (to be created during open())
        self._figure: Figure | None = None
        self._lick_axis: Axes | None = None
        self._valve_axis: Axes | None = None
        self._speed_axis: Axes | None = None

        # Running speed threshold and duration threshold lines
        self._speed_threshold_line: Line2D | None = None
        self._duration_threshold_line: Line2D | None = None

        # Text annotations
        self._speed_threshold_text: Text | None = None
        self._duration_threshold_text: Text | None = None

        # Tracks if the visualizer is opened
        self._is_open: bool = False
        self._once: bool = True

    def open(self) -> None:
        """Opens the visualization window and initializes all matplotlib components.

        This method must be called before any visualization updates can occur.
        """
        if self._is_open:
            return  # Already open

        # Creates the figure with three subplots sharing the same x-axis
        self._figure, (self._lick_axis, self._valve_axis, self._speed_axis) = plt.subplots(
            3,
            1,
            figsize=(10, 8),
            sharex=True,
            num="Runtime Behavior Visualizer",
            # Ensures that the third subplot is thrice as tall
            gridspec_kw={"hspace": 0.3, "left": 0.15, "height_ratios": [1, 1, 3]},
        )

        # Sets consistent y-label padding for all axes
        self._lick_axis.yaxis.labelpad = 15
        self._valve_axis.yaxis.labelpad = 15
        self._speed_axis.yaxis.labelpad = 15

        # Set up axes properties
        # Lick axis
        self._lick_axis.set_title("Lick Sensor State", fontdict=_fontdict_title)
        self._lick_axis.set_ylim(-0.05, 1.05)
        self._lick_axis.set_ylabel("Lick State", fontdict=_fontdict_axis_label)
        self._lick_axis.set_xlabel("")
        self._lick_axis.yaxis.set_major_locator(FixedLocator([0, 1]))
        self._lick_axis.yaxis.set_major_formatter(FixedFormatter(["No Lick", "Lick"]))

        # Valve axis
        self._valve_axis.set_title("Reward Valve State", fontdict=_fontdict_title)
        self._valve_axis.set_ylim(-0.05, 1.05)
        self._valve_axis.set_ylabel("Valve State", fontdict=_fontdict_axis_label)
        self._valve_axis.set_xlabel("")
        self._valve_axis.yaxis.set_major_locator(FixedLocator([0, 1]))
        self._valve_axis.yaxis.set_major_formatter(FixedFormatter(["Closed", "Open"]))

        # Speed axis
        self._speed_axis.set_title("Average Running Speed", fontdict=_fontdict_title)
        self._speed_axis.set_ylim(-2, 42)
        self._speed_axis.set_ylabel("Running speed (cm/s)", fontdict=_fontdict_axis_label)
        self._speed_axis.set_xlabel("Time (s)", fontdict=_fontdict_axis_label)
        self._speed_axis.yaxis.set_major_locator(MaxNLocator(nbins="auto", integer=False))
        self._speed_axis.xaxis.set_major_locator(MaxNLocator(nbins="auto", integer=True))

        # Sets x-limits for all axes (shared x-axis)
        self._speed_axis.set_xlim(-self._time_window, 0)

        # Hides x-tick labels for top plots
        plt.setp(self._lick_axis.get_xticklabels(), visible=False)
        plt.setp(self._valve_axis.get_xticklabels(), visible=False)

        # Aligns all y-labels
        self._figure.align_ylabels([self._lick_axis, self._valve_axis, self._speed_axis])

        # Creates the plot artists
        # Lick plot
        (self._lick_line,) = self._lick_axis.plot(
            self._timestamps,
            self._lick_data,
            drawstyle="steps-post",
            color=_plt_palette("red"),
            linewidth=2,
            alpha=1.0,
            linestyle="solid",
        )

        # Valve plot
        (self._valve_line,) = self._valve_axis.plot(
            self._timestamps,
            self._valve_data,
            drawstyle="steps-post",
            color=_plt_palette("blue"),
            linewidth=2,
            alpha=1.0,
            linestyle="solid",
        )

        # Speed plot
        (self._speed_line,) = self._speed_axis.plot(
            self._timestamps, self._speed_data, color=_plt_palette("green"), linewidth=2, alpha=1.0, linestyle="solid"
        )

        # Running speed and duration threshold
        self._speed_threshold_line = self._speed_axis.axhline(
            y=0.05, color=_plt_palette("black"), linestyle="dashed", linewidth=1.5, alpha=0.5, visible=False
        )
        self._duration_threshold_line = self._speed_axis.axvline(
            x=-0.05, color=_plt_palette("black"), linestyle="dashed", linewidth=1.5, alpha=0.5, visible=False
        )

        # Adds text annotations for speed and duration thresholds
        self._speed_threshold_text = self._speed_axis.text(
            -self._time_window + 0.5,  # x position: left edge and padding
            40,  # y position: near top of plot
            f"Target speed: {0:.2f} cm/s",
            fontdict=_fontdict_legend,
            verticalalignment="top",
            bbox=dict(facecolor="white", alpha=1.0, edgecolor="none", pad=3),
        )

        self._duration_threshold_text = self._speed_axis.text(
            -self._time_window + 0.5,  # x position: left edge and padding
            35.5,  # y position: below speed text
            f"Target duration: {0:.2f} s",
            fontdict=_fontdict_legend,
            verticalalignment="top",
            bbox=dict(facecolor="white", alpha=1.0, edgecolor="none", pad=3),
        )

        # Generates the figure object and updates it
        plt.show(block=False)
        self._figure.canvas.draw()
        self._figure.canvas.flush_events()

        self._is_open = True

    def __del__(self) -> None:
        """Ensures that the visualization is terminated before the instance is garbage-collected."""
        self.close()

    def update(self) -> None:
        """Updates the visualization plot managed by the instance to include the data acquired since the last update()
        call.

        Notes:
            The method has an internal update frequency limiter and is designed to be called without any external
            update frequency control.
        """
        # Does not do anything until the figure is opened (created)
        if not self._is_open:
            return

        # Ensures the plot is not updated any faster than necessary to resolve the time_step used by the plot
        if self._update_timer.elapsed < self._time_step:
            return

        self._update_timer.reset()

        # Replaces the oldest timestamp data with the current data.
        self._sample_data()

        # Updates the artists with new data
        self._lick_line.set_data(self._timestamps, self._lick_data)
        self._valve_line.set_data(self._timestamps, self._valve_data)
        self._speed_line.set_data(self._timestamps, self._speed_data)

        # Renders the changes
        self._figure.canvas.draw()
        self._figure.canvas.flush_events()

    def update_run_training_thresholds(self, speed_threshold: np.float64, duration_threshold: np.float64) -> None:
        """Updates the running speed and duration threshold lines to use the input anchor values.

        Args:
            speed_threshold: The speed, in centimeter per second, the animal needs to maintain to get water rewards.
            duration_threshold: The duration, in milliseconds, the animal has to maintain the above-threshold speed to
                get water rewards.
        """
        # Does not do anything until the figure is opened (created)
        if not self._is_open:
            return

        # Converts from milliseconds to seconds
        duration_threshold /= 1000

        # Updates line position(s)
        self._speed_threshold_line.set_ydata([speed_threshold, speed_threshold])
        self._duration_threshold_line.set_xdata([-duration_threshold, -duration_threshold])

        # Updates text annotations with current threshold values
        self._speed_threshold_text.set_text(f"Target speed: {speed_threshold:.2f} cm/s")
        self._duration_threshold_text.set_text(f"Target duration: {duration_threshold:.2f} s")

        # This ensures the visibility is only changed once during runtime
        if self._once:
            self._speed_threshold_line.set_visible(True)
            self._duration_threshold_line.set_visible(True)
            self._once = False

        # Renders the changes
        self._figure.canvas.draw()
        self._figure.canvas.flush_events()

    def close(self) -> None:
        """Closes the visualized figure and cleans up the resources used by the instance during runtime."""
        if self._is_open and self._figure is not None:
            plt.close(self._figure)
            self._is_open = False

    def _sample_data(self) -> None:
        """Updates the visualization data arrays with the data accumulated since the last visualization update."""
        # Rolls arrays by one position to the left, so the first element becomes the last
        self._valve_data = np.roll(self._valve_data, shift=-1)
        self._lick_data = np.roll(self._lick_data, shift=-1)
        self._speed_data = np.roll(self._speed_data, shift=-1)

        # Replaces the last element (previously the first or 'oldest' value) with new data:

        # If the runtime has detected at least one lick event since the last visualizer update, emits a lick tick.
        if self._lick_event:
            self._lick_data[-1] = self._event_tick_true
        else:
            self._lick_data[-1] = self._event_tick_false
        self._lick_event = False  # Resets the lick event flag

        # If the runtime has detected at least one water reward (valve) event since the last visualizer update, emits a
        # valve activation tick.
        if self._valve_event:
            self._valve_data[-1] = self._event_tick_true
        else:
            self._valve_data[-1] = self._event_tick_false
        self._valve_event = False  # Resets the valve event flag

        # The speed value is updated ~every 50 milliseconds. Until the update timeout is exhausted, at each graph
        # update cycle the last speed point is overwritten with the previous speed point. This generates a
        # sequence of at most 2 identical speed readouts and is not noticeable to the user.
        self._speed_data[-1] = self._running_speed

    def add_lick_event(self) -> None:
        """Instructs the visualizer to render a new lick event during the next update cycle."""
        self._lick_event = True

    def add_valve_event(self) -> None:
        """Instructs the visualizer to render a new valve activation (reward) event during the next update cycle."""
        self._valve_event = True

    def update_running_speed(self, running_speed: np.float64) -> None:
        """Instructs the visualizer to render the provided running speed datapoint during the next update cycle."""
        self._running_speed = running_speed
