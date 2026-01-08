"""Provides the Visualizer class that renders the animal's task performance data in real time during training and
experiment runtimes.
"""

from enum import IntEnum
from typing import TYPE_CHECKING

import numpy as np
import matplotlib as mpl

mpl.use("QtAgg")  # Uses QT backend for performance and compatibility with Linux

from ataraxis_time import PrecisionTimer
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, FixedLocator, FixedFormatter
from matplotlib.patches import Rectangle
from ataraxis_base_utilities import console

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from matplotlib.axes import Axes
    from matplotlib.text import Text
    from matplotlib.lines import Line2D
    from matplotlib.figure import Figure

# Updates plotting dictionaries to preferentially use Arial text style and specific sizes for different text elements
# in plots. General parameters and the font size for axes' tick numbers.
plt.rcParams.update({"font.family": "Arial", "font.weight": "normal", "xtick.labelsize": 16, "ytick.labelsize": 16})
_fontdict_axis_label = {"family": "Arial", "weight": "normal", "size": 18}  # Axis label fonts.
_fontdict_title = {"family": "Arial", "weight": "normal", "size": 20}  # Title fonts.
_fontdict_legend = {"family": "Arial", "weight": "normal", "size": 14}  # Legend fonts.

# Initializes dictionaries to map colloquial names to specific linestyle and color parameters.
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


class VisualizerMode(IntEnum):
    """Defines the display modes for the BehaviorVisualizer."""

    LICK_TRAINING = 0
    """Displays only lick sensor and valve plots."""
    RUN_TRAINING = 1
    """Displays lick, valve, and running speed plots."""
    EXPERIMENT = 2
    """Displays all plots including the trial performance panel."""


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
        # Fallback to appease mypy. Should not be reachable.
        raise KeyError(message) from None  # pragma: no cover


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
        # Fallback to appease mypy. Should not be reachable.
        raise KeyError(message) from None  # pragma: no cover


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
        _mode: The runtime mode that determines the visualizer layout.
        _trial_axis: The axis for the trial performance panel (only in experiment mode).
        _reinforcing_trials: Stores the outcomes of the last 20 reinforcing trials. Values are -1 for empty,
            0 for failed, 1 for succeeded, 2 for guided.
        _aversive_trials: Stores the outcomes of the last 20 aversive trials. Values are -1 for empty, 0 for failed,
            1 for succeeded, 2 for guided.
        _reinforcing_index: The current write index for the reinforcing trials circular buffer.
        _aversive_index: The current write index for the aversive trials circular buffer.
        _reinforcing_rectangles: The rectangle patches for visualizing reinforcing trial outcomes.
        _aversive_rectangles: The rectangle patches for visualizing aversive trial outcomes.
    """

    # Pre-initializes NumPy event ticks to slightly reduce cyclic visualizer update speed.
    _event_tick_true = np.uint8(1)
    _event_tick_false = np.uint8(0)

    def __init__(
        self,
    ) -> None:
        # Currently, the class is statically configured to visualize the sliding window of 10 seconds updated every
        # 25 ms.
        self._time_window: int = 10
        self._time_step: int = 25
        self._update_timer = PrecisionTimer("ms")

        # Pre-creates the structures used to store the displayed data during visualization runtime.
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

        # Running speed threshold and duration threshold lines.
        self._speed_threshold_line: Line2D | None = None
        self._duration_threshold_line: Line2D | None = None

        # Text annotations.
        self._speed_threshold_text: Text | None = None
        self._duration_threshold_text: Text | None = None

        self._is_open: bool = False
        self._once: bool = True

        self._mode: VisualizerMode | int = VisualizerMode.EXPERIMENT

        # These arrays store trial outcomes as circular buffers with values: -1=empty, 0=failed, 1=succeeded, 2=guided.
        self._reinforcing_trials: NDArray[np.int8] = np.full(20, -1, dtype=np.int8)
        self._aversive_trials: NDArray[np.int8] = np.full(20, -1, dtype=np.int8)
        self._reinforcing_index: int = 0
        self._aversive_index: int = 0

        self._trial_axis: Axes | None = None
        self._reinforcing_rectangles: list[Rectangle] = []
        self._aversive_rectangles: list[Rectangle] = []

    def open(self, mode: VisualizerMode | int = VisualizerMode.EXPERIMENT) -> None:
        """Opens the visualization window and initializes all matplotlib components.

        Notes:
            This method must be called before any visualization updates can occur.

        Args:
            mode: The display mode that determines the subplot layout. Must be a valid VisualizerMode
                enumeration member.
        """
        if self._is_open:
            return

        self._mode = mode

        # Creates the figure with a mode-dependent subplot layout.
        if mode == VisualizerMode.LICK_TRAINING:
            self._figure, (self._lick_axis, self._valve_axis) = plt.subplots(
                2,
                1,
                figsize=(10, 5),
                sharex=True,
                num="Runtime Behavior Visualizer",
                gridspec_kw={"hspace": 0.3, "left": 0.15, "height_ratios": [1, 1]},
            )
            self._speed_axis = None
            self._trial_axis = None
        elif mode == VisualizerMode.RUN_TRAINING:
            self._figure, (self._lick_axis, self._valve_axis, self._speed_axis) = plt.subplots(
                3,
                1,
                figsize=(10, 8),
                sharex=True,
                num="Runtime Behavior Visualizer",
                gridspec_kw={"hspace": 0.3, "left": 0.15, "height_ratios": [1, 1, 3]},
            )
            self._trial_axis = None
        else:  # VisualizerMode.EXPERIMENT
            self._figure, (self._lick_axis, self._valve_axis, self._speed_axis, self._trial_axis) = plt.subplots(
                4,
                1,
                figsize=(10, 10),
                num="Runtime Behavior Visualizer",
                gridspec_kw={"hspace": 0.3, "left": 0.15, "height_ratios": [1, 1, 3, 2]},
            )

        # Padding value ensures that the y-labels are aligned across all axes.
        self._lick_axis.yaxis.labelpad = 15
        self._valve_axis.yaxis.labelpad = 15
        if self._speed_axis is not None:
            self._speed_axis.yaxis.labelpad = 15

        self._lick_axis.set_title("Lick Sensor State", fontdict=_fontdict_title)
        self._lick_axis.set_ylim(-0.05, 1.05)
        self._lick_axis.set_ylabel("Lick State", fontdict=_fontdict_axis_label)
        self._lick_axis.set_xlabel("")
        self._lick_axis.yaxis.set_major_locator(FixedLocator([0, 1]))
        self._lick_axis.yaxis.set_major_formatter(FixedFormatter(["No Lick", "Lick"]))

        self._valve_axis.set_title("Reward Valve State", fontdict=_fontdict_title)
        self._valve_axis.set_ylim(-0.05, 1.05)
        self._valve_axis.set_ylabel("Valve State", fontdict=_fontdict_axis_label)
        self._valve_axis.set_xlabel("")
        self._valve_axis.yaxis.set_major_locator(FixedLocator([0, 1]))
        self._valve_axis.yaxis.set_major_formatter(FixedFormatter(["Closed", "Open"]))

        # Configures the speed axis, which only exists in RUN_TRAINING and experiment modes.
        if self._speed_axis is not None:
            self._speed_axis.set_title("Average Running Speed", fontdict=_fontdict_title)
            self._speed_axis.set_ylim(-2, 42)
            self._speed_axis.set_ylabel("Running speed (cm/s)", fontdict=_fontdict_axis_label)
            self._speed_axis.set_xlabel("Time (s)", fontdict=_fontdict_axis_label)
            self._speed_axis.yaxis.set_major_locator(MaxNLocator(nbins="auto", integer=False))
            self._speed_axis.xaxis.set_major_locator(MaxNLocator(nbins="auto", integer=True))
            self._speed_axis.set_xlim(-self._time_window, 0)
            plt.setp(self._lick_axis.get_xticklabels(), visible=False)
            plt.setp(self._valve_axis.get_xticklabels(), visible=False)
            self._figure.align_ylabels([self._lick_axis, self._valve_axis, self._speed_axis])
        else:
            # In LICK_TRAINING mode, the valve axis is the bottom plot and shows the x-axis labels.
            self._valve_axis.set_xlabel("Time (s)", fontdict=_fontdict_axis_label)
            self._valve_axis.xaxis.set_major_locator(MaxNLocator(nbins="auto", integer=True))
            self._valve_axis.set_xlim(-self._time_window, 0)
            plt.setp(self._lick_axis.get_xticklabels(), visible=False)
            self._figure.align_ylabels([self._lick_axis, self._valve_axis])

        (self._lick_line,) = self._lick_axis.plot(
            self._timestamps,
            self._lick_data,
            drawstyle="steps-post",
            color=_plt_palette("red"),
            linewidth=2,
            alpha=1.0,
            linestyle="solid",
        )

        (self._valve_line,) = self._valve_axis.plot(
            self._timestamps,
            self._valve_data,
            drawstyle="steps-post",
            color=_plt_palette("blue"),
            linewidth=2,
            alpha=1.0,
            linestyle="solid",
        )

        # Creates the speed plot and threshold lines for RUN_TRAINING and experiment modes.
        if self._speed_axis is not None:
            (self._speed_line,) = self._speed_axis.plot(
                self._timestamps,
                self._speed_data,
                color=_plt_palette("green"),
                linewidth=2,
                alpha=1.0,
                linestyle="solid",
            )

            self._speed_threshold_line = self._speed_axis.axhline(
                y=0.05, color=_plt_palette("black"), linestyle="dashed", linewidth=1.5, alpha=0.5, visible=False
            )
            self._duration_threshold_line = self._speed_axis.axvline(
                x=-0.05, color=_plt_palette("black"), linestyle="dashed", linewidth=1.5, alpha=0.5, visible=False
            )

            self._speed_threshold_text = self._speed_axis.text(
                -self._time_window + 0.5,  # x position: left edge and padding
                40,  # y position: near top of plot
                f"Target speed: {0:.2f} cm/s",
                fontdict=_fontdict_legend,
                verticalalignment="top",
                bbox={"facecolor": "white", "alpha": 1.0, "edgecolor": "none", "pad": 3},
            )

            self._duration_threshold_text = self._speed_axis.text(
                -self._time_window + 0.5,  # x position: left edge and padding
                35.5,  # y position: below speed text
                f"Target duration: {0:.2f} s",
                fontdict=_fontdict_legend,
                verticalalignment="top",
                bbox={"facecolor": "white", "alpha": 1.0, "edgecolor": "none", "pad": 3},
            )

        # Sets up the trial performance panel, which only exists in experiment modes.
        if self._trial_axis is not None:
            self._setup_trial_axis()

        plt.show(block=False)
        self._figure.canvas.draw()
        self._figure.canvas.flush_events()

        self._is_open = True

    def __del__(self) -> None:
        """Ensures that the visualization is terminated before the instance is garbage-collected."""
        self.close()

    def update(self) -> None:
        """Re-renders the visualization plot managed by the instance to include the data acquired since the last
        update() call.

        Notes:
            The method has an internal update frequency limiter and is designed to be called without any external
            update frequency control.
        """
        # Does not do anything until the figure is opened (created)
        if not self._is_open:
            return

        # Ensures the plot is not updated any faster than necessary to resolve the time_step used by the plot.
        if self._update_timer.elapsed < self._time_step:
            return

        self._update_timer.reset()

        # Replaces the oldest timestamp data with the current data.
        self._sample_data()

        # Updates the artists with new data.
        self._lick_line.set_data(self._timestamps, self._lick_data)  # type: ignore[union-attr]
        self._valve_line.set_data(self._timestamps, self._valve_data)  # type: ignore[union-attr]
        if self._speed_line is not None:
            self._speed_line.set_data(self._timestamps, self._speed_data)

        # Renders the changes.
        self._figure.canvas.draw()  # type: ignore[union-attr]
        self._figure.canvas.flush_events()  # type: ignore[union-attr]

    def update_run_training_thresholds(self, speed_threshold: np.float64, duration_threshold: np.float64) -> None:
        """Updates the running speed and duration threshold lines to use the input anchor values.

        Args:
            speed_threshold: The speed, in centimeter per second, the animal needs to maintain to get water rewards.
            duration_threshold: The duration, in milliseconds, the animal has to maintain the above-threshold speed to
                get water rewards.
        """
        # Does not do anything until the figure is opened (created) or if speed axis doesn't exist.
        if not self._is_open or self._speed_axis is None:
            return

        # Converts from milliseconds to seconds.
        duration_threshold /= 1000

        # Updates line positions.
        self._speed_threshold_line.set_ydata([speed_threshold, speed_threshold])  # type: ignore[union-attr]
        self._duration_threshold_line.set_xdata([-duration_threshold, -duration_threshold])  # type: ignore[union-attr]

        # Updates text annotations with current threshold values.
        self._speed_threshold_text.set_text(f"Target speed: {speed_threshold:.2f} cm/s")  # type: ignore[union-attr]
        self._duration_threshold_text.set_text(  # type: ignore[union-attr]
            f"Target duration: {duration_threshold:.2f} s"
        )

        # Ensures the visibility is only changed once during runtime.
        if self._once:
            self._speed_threshold_line.set_visible(True)  # type: ignore[union-attr]
            self._duration_threshold_line.set_visible(True)  # type: ignore[union-attr]
            self._once = False

        # Renders the changes.
        self._figure.canvas.draw()  # type: ignore[union-attr]
        self._figure.canvas.flush_events()  # type: ignore[union-attr]

    def close(self) -> None:
        """Closes the visualized figure and cleans up the resources used by the instance during runtime."""
        if self._is_open and self._figure is not None:
            plt.close(self._figure)
            self._is_open = False

    def _sample_data(self) -> None:
        """Updates the visualization data arrays with the data accumulated since the last visualization update."""
        # Rolls arrays by one position to the left, so the first element becomes the last.
        self._valve_data = np.roll(self._valve_data, shift=-1)
        self._lick_data = np.roll(self._lick_data, shift=-1)

        # Replaces the last element (previously the first or 'oldest' value) with new data.

        # If the runtime has detected at least one lick event since the last visualizer update, emits a lick tick.
        if self._lick_event:
            self._lick_data[-1] = self._event_tick_true
        else:
            self._lick_data[-1] = self._event_tick_false
        self._lick_event = False  # Resets the lick event flag.

        # If the runtime has detected at least one water reward (valve) event since the last visualizer update, emits a
        # valve activation tick.
        if self._valve_event:
            self._valve_data[-1] = self._event_tick_true
        else:
            self._valve_data[-1] = self._event_tick_false
        self._valve_event = False  # Resets the valve event flag.

        # The speed value is updated ~every 50 milliseconds. Until the update timeout is exhausted, at each graph
        # update cycle the last speed point is overwritten with the previous speed point. This generates a
        # sequence of at most 2 identical speed readouts and is not noticeable to the user. Only updates if speed axis
        # exists (not in LICK_TRAINING mode).
        if self._speed_axis is not None:
            self._speed_data = np.roll(self._speed_data, shift=-1)
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

    def _setup_trial_axis(self) -> None:
        """Initializes the trial performance panel with empty rectangle patches.

        This method creates a 2-row visualization showing reinforcing (bottom) and aversive (top) trial outcomes
        as colored bars. Each row contains 20 rectangle slots that are filled as trials complete.
        """
        if self._trial_axis is None:
            return

        self._trial_axis.set_title("Trial Performance (Last 20 Trials)", fontdict=_fontdict_title)
        self._trial_axis.set_xlim(-0.5, 19.5)
        self._trial_axis.set_ylim(-0.1, 1.1)
        self._trial_axis.set_yticks([0.25, 0.75])
        self._trial_axis.set_yticklabels(["Reinforcing", "Aversive"])
        self._trial_axis.yaxis.labelpad = 15
        self._trial_axis.set_xticks(range(0, 20, 2))
        self._trial_axis.set_xlabel("Trial Position (0 = oldest, 19 = newest)", fontdict=_fontdict_axis_label)
        self._trial_axis.axhline(y=0.5, color=_plt_palette("gray"), linestyle="-", linewidth=0.5, alpha=0.5)

        # Creates the reinforcing trial rectangles in the bottom row.
        self._reinforcing_rectangles = []
        for i in range(20):
            rect = Rectangle(
                xy=(i - 0.4, 0.05),
                width=0.8,
                height=0.4,
                facecolor=_plt_palette("gray"),
                edgecolor="none",
                alpha=0.3,
                visible=False,
            )
            self._trial_axis.add_patch(rect)
            self._reinforcing_rectangles.append(rect)

        # Creates the aversive trial rectangles in the top row.
        self._aversive_rectangles = []
        for i in range(20):
            rect = Rectangle(
                xy=(i - 0.4, 0.55),
                width=0.8,
                height=0.4,
                facecolor=_plt_palette("gray"),
                edgecolor="none",
                alpha=0.3,
                visible=False,
            )
            self._trial_axis.add_patch(rect)
            self._aversive_rectangles.append(rect)

    def add_trial_outcome(self, *, is_aversive: bool, succeeded: bool, was_guided: bool) -> None:
        """Records a trial outcome and updates the trial performance visualization.

        Args:
            is_aversive: Determines whether the trial was an aversive (gas puff) trial. If False, the trial is
                treated as a reinforcing (water reward) trial.
            succeeded: Determines whether the animal succeeded in the trial. For reinforcing trials, success means
                the animal received a reward. For aversive trials, success means the animal avoided the puff.
            was_guided: Determines whether the trial was in guidance mode (automatic rewards/puffs).
        """
        if self._trial_axis is None:
            return

        # Maps the boolean outcome flags to integer values: 2=guided, 1=success, 0=failure.
        if was_guided:
            outcome = np.int8(2)
        elif succeeded:
            outcome = np.int8(1)
        else:
            outcome = np.int8(0)

        if is_aversive:
            self._aversive_trials[self._aversive_index] = outcome
            self._update_trial_rectangle(
                rectangles=self._aversive_rectangles, index=self._aversive_index, outcome=outcome
            )
            self._aversive_index = (self._aversive_index + 1) % 20
        else:
            self._reinforcing_trials[self._reinforcing_index] = outcome
            self._update_trial_rectangle(
                rectangles=self._reinforcing_rectangles, index=self._reinforcing_index, outcome=outcome
            )
            self._reinforcing_index = (self._reinforcing_index + 1) % 20

    @staticmethod
    def _update_trial_rectangle(rectangles: list[Rectangle], index: int, outcome: np.int8) -> None:
        """Updates a single trial rectangle based on the outcome value.

        Args:
            rectangles: The list of rectangle patches (either reinforcing or aversive).
            index: The index of the trial in the circular buffer (0-19).
            outcome: The outcome value (-1=empty, 0=failure, 1=success, 2=guided).
        """
        if index >= len(rectangles):
            return

        rect = rectangles[index]

        # Sets rectangle color based on outcome: green=success, red=failure, blue=guided.
        if outcome == 1:
            rect.set_facecolor(_plt_palette("green"))
        elif outcome == 0:
            rect.set_facecolor(_plt_palette("red"))
        else:
            rect.set_facecolor(_plt_palette("blue"))

        rect.set_alpha(1.0)
        rect.set_visible(True)
