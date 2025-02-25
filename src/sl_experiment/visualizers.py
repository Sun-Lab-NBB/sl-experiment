"""This module provides Visualizer classes to render hardware module data in real time."""

import numpy as np
import matplotlib
matplotlib.use("QtAgg")  # Uses QT backend for performance and compatibility with Linux

from matplotlib.ticker import MaxNLocator
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from ataraxis_base_utilities import console, LogLevel
from ataraxis_time import PrecisionTimer
from ataraxis_data_structures import SharedMemoryArray


# Updates plotting dictionaries to preferentially use Arial text style and specific sizes for different text elements
# in plots:
# General parameters and the font size for axes' tick numbers
plt.rcParams.update({"font.family": "Arial", "font.weight": "normal", "xtick.labelsize": 16, "ytick.labelsize": 16})
_fontdict_axis_label = {"family": "Arial", "weight": "normal", "size": 18}  # Axis label fonts
_fontdict_title = {"family": "Arial", "weight": "normal", "size": 20}  # Title fonts
_fontdict_legend = {"family": "Arial", "weight": "normal", "size": 16}  # Legend fonts

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
    """Converts colloquial line style names to pyplot's 'lifestyle' string-codes.

    Args:
        line_style: Colloquial name for the line style to be used. Options are 'solid', 'dashed', 'dotdashed' and
            'dotted'.

    Returns:
        The string-code for the requested line style.

    Raises:
        KeyError: If the provided line style is not recognized.
    """

    try:
        return str(_line_style_dict[line_style])
    except KeyError:
        message = (
            f"Unexpected line style name '{line_style}' encountered when converting the colloquial line style pyplot "
            f"linestyle string. Provide one of the supported line style arguments: "
            f"{', '.join(_line_style_dict.keys())}."
        )
        console.error(message=message, error=KeyError)
        # Fallback to appease mypy, should not be reachable
        raise KeyError(message)  # pragma: no cover


class BehaviorVisualizer:
    """Visualizes behavioral data in real-time during experiment or training runtimes.

    Primarily, this class is used to visualize licks, reward delivery, and running speed data while animals perform
    experiment or training sessions in the Mesoscope-VR system. Note, the class is statically configured to generate
    the plots for all supported data streams, even if some of them are not used during a particular training session.

    Args:
        lick_tracker: The SharedMemoryArray instance exposed by the LickInterface class that communicates the lick
            sensor status in real time.
        valve_tracker: The SharedMemoryArray instance exposed by the ValveInterface class that communicates the solenoid
            valve state in real time.
        speed_tracker: The SharedMemoryArray instance exposed by the EncoderInterface class that communicates the
            average running speed of the animal calculated over 100-millisecond windows.
        time_window: The time window, in seconds, for which to plot the data. This determines how many seconds of the
            past data to include in the plots, relative to the current time.
        lick_threshold. The minimum lick sensor readout, in raw Analog-to-Digital Converter (ADC) units, that is
            interpreted as a lick. This is used to plot a static horizontal bar to indicate the lick detection threshold
            to the user.
        speed_threshold: The minimum average running speed, in centimeters per second, that is considered 'satisfactory'
            during run training. This value changes depending on animal's performance and is used to render a horizontal
            line to indicate the speed threshold to the user.
        speed_duration_threshold: The minimum duration, in seconds, the animal should maintain the speed that is above
            the 'speed_threshold' to satisfy the current run training conditions. This is used together with the
            'speed_threshold' value to indicate when the animal is performing satisfactorily during training.

    Attributes:
        _minimum_time: The minimum time, in milliseconds, to include in the plots, relative to the current time.
        _lick_threshold: The minimum lick sensor readout, in raw ADC units, that is interpreted as a lick.
        _speed_threshold: The minimum average running speed, in centimeters per second, that is considered
            'satisfactory' during run training.
        _speed_duration_threshold: The minimum duration, in seconds, the animal should maintain the speed that is above
            the 'speed_threshold' to satisfy the current run training conditions.
        _lick_tracker: The SharedMemoryArray instance exposed by the LickInterface class that communicates the lick
            sensor status in real time.
        _valve_tracker: The SharedMemoryArray instance exposed by the ValveInterface class that communicates the
            solenoid valve state in real time.
        _speed_tracker: The SharedMemoryArray instance exposed by the EncoderInterface class that communicates the
            average running speed of the animal calculated over 100-millisecond windows.
        _timestamps: A numpy array that stores the timestamps of the displayed data during visualization runtime. The
            timestamps are calculated at class initialization and are kept constant afterward.
        _lick_data: A numpy array that stores the lick sensor state readouts during visualization runtime.
        _valve_data: A numpy array that stores the solenoid valve state readouts during visualization runtime.
        _speed_data: A numpy array that stores the average running speed readouts during visualization runtime.
        _total_volume: A float64 value that stores the total volume of water dispensed by the valve during runtime.
        _figure: A matplotlib figure instance used to display the plots during visualization runtime.
        _lick_axis: The axis object used to plot the lick sensor data during visualization runtime.
        _valve_axis: The axis object used to plot the solenoid valve data during visualization runtime.
        _speed_axis: The axis object used to plot the average running speed data during visualization runtime.
    """

    def __init__(
        self,
        lick_tracker: SharedMemoryArray,
        valve_tracker: SharedMemoryArray,
        speed_tracker: SharedMemoryArray,
        time_window: int = 60,
        lick_threshold: int = 1000,
        speed_threshold: float = 1.0,
        speed_duration_threshold: int = 100,
    ) -> None:
        # Saves runtime configuration data to class attributes
        self._minimum_time: int = -time_window * 1000  # Converts to milliseconds and flips to negative
        self._lick_threshold: int = lick_threshold
        self._speed_threshold: float = speed_threshold
        self._speed_duration_threshold: int = speed_duration_threshold

        # Data trackers
        self._lick_tracker = lick_tracker
        self._valve_tracker = valve_tracker
        self._speed_tracker = speed_tracker

        # Precreates the structures used to store the displayed data during visualization runtime
        self._timestamps = np.arange(start=self._minimum_time, stop=0, step=50, dtype=np.int32)
        self._lick_data = np.zeros_like(a=self._timestamps, dtype=np.uint16)
        self._valve_data = np.zeros_like(a=self._timestamps, dtype=np.uint8)
        self._speed_data = np.zeros_like(a=self._timestamps, dtype=np.float64)
        self._total_volume: np.float64 = np.float64(0)
        self._last_volume: np.float64 = np.float64(0)

        # Animation objects
        self._animation = None

        # Line objects (to be created during initialization)
        self._lick_line = None
        self._lick_threshold_line = None
        self._valve_line = None
        self._speed_line = None
        self._volume_text = None

        # Figure objects
        self._initialized = False
        self._figure = None
        self._lick_axis = None
        self._valve_axis = None
        self._speed_axis = None

    def initialize(self) -> None:
        """Initialize the visualization figure and axes.

        This creates a figure with three subplots that share the same x-axis
        but maintain independent y-axes, titles, and styling.
        """
        if self._initialized:
            return

        # Create the figure with three subplots sharing the same x-axis
        # The sharex=True parameter is crucial - it makes all subplots share the same x-axis
        self._figure, (self._lick_axis, self._valve_axis, self._speed_axis) = plt.subplots(
            3, 1, figsize=(10, 8), sharex=True, gridspec_kw={'hspace': 0.3, 'left': 0.15}
        )

        # Set consistent y-label padding for all axes to ensure alignment
        self._lick_axis.yaxis.labelpad = 15
        self._valve_axis.yaxis.labelpad = 15
        self._speed_axis.yaxis.labelpad = 15

        # Set up axes properties once
        self._setup_axes()

        # Create the plot artists (these will be updated by the animation)
        self._setup_plot_artists()

        # Initialize animation with blitting
        self._animation = animation.FuncAnimation(
            self._figure,
            self._animate,
            init_func=self._init_animation,
            interval=100,
            blit=True,  # Use blitting for maximum performance
            cache_frame_data=False,  # Don't cache frames (real-time data)
        )

        # Show figure
        plt.show(block=False)

        # Process initial events to make window appear
        plt.pause(0.001)

        self._initialized = True

    def _setup_axes(self) -> None:
        """Configure axes properties once during initialization."""
        # Lick axis
        self._lick_axis.set_title("Lick Sensor State", fontdict=_fontdict_title)
        self._lick_axis.set_ylim(-0.05, 1.05)
        self._lick_axis.set_ylabel("Lick State", fontdict=_fontdict_axis_label)
        self._lick_axis.set_xlabel("")
        self._lick_axis.yaxis.set_major_locator(plt.FixedLocator([0, 1]))
        self._lick_axis.yaxis.set_major_formatter(plt.FixedFormatter(["No Lick", "Lick"]))

        # Valve axis
        self._valve_axis.set_title("Reward Valve State", fontdict=_fontdict_title)
        self._valve_axis.set_ylim(-0.05, 1.05)
        self._valve_axis.set_ylabel("Valve State", fontdict=_fontdict_axis_label)
        self._valve_axis.set_xlabel("")
        self._valve_axis.yaxis.set_major_locator(plt.FixedLocator([0, 1]))
        self._valve_axis.yaxis.set_major_formatter(plt.FixedFormatter(["Closed", "Open"]))

        # Speed axis
        self._speed_axis.set_title("Average Running Speed", fontdict=_fontdict_title)
        self._speed_axis.set_ylim(-2, 32)
        self._speed_axis.set_ylabel("Running speed (cm/s)", fontdict=_fontdict_axis_label)
        self._speed_axis.set_xlabel("Time (ms)", fontdict=_fontdict_axis_label)
        self._speed_axis.yaxis.set_major_locator(MaxNLocator(nbins="auto", integer=False))
        self._speed_axis.xaxis.set_major_locator(MaxNLocator(nbins="auto", integer=True))

        # Set x-limits for all axes (shared x-axis)
        self._speed_axis.set_xlim(self._minimum_time - 1, 1)

        # Hide x-tick labels for top plots
        plt.setp(self._lick_axis.get_xticklabels(), visible=False)
        plt.setp(self._valve_axis.get_xticklabels(), visible=False)

        # Align y-labels
        self._figure.align_ylabels([self._lick_axis, self._valve_axis, self._speed_axis])

    def _setup_plot_artists(self) -> None:
        """Create the artists (plot elements) that will be animated."""
        # Create lick plot artists
        self._lick_line, = self._lick_axis.plot(
            self._timestamps, self._lick_data, drawstyle="steps-post", color=_plt_palette("red"),
            linewidth=2, alpha=1.0, linestyle="solid"
        )

        # Create valve plot artists
        self._valve_line, = self._valve_axis.plot(
            self._timestamps, self._valve_data, drawstyle="steps-post", color=_plt_palette("blue"),
            linewidth=2, alpha=1.0, linestyle="solid"
        )

        # Create volume text artist
        self._volume_text = self._valve_axis.text(
            0.02, 0.75, "", transform=self._valve_axis.transAxes,
            fontdict=_fontdict_legend, horizontalalignment='left',
            verticalalignment='top', bbox=dict(facecolor="white", alpha=0.7,
                                               pad=3.0, boxstyle="round,pad=0.3")
        )

        # Create speed plot artists
        self._speed_line, = self._speed_axis.plot(
            self._timestamps, self._speed_data, color=_plt_palette("green"),
            linewidth=2, alpha=1.0, linestyle="solid"
        )

    def _init_animation(self):
        """Initialize the animation for blitting.

        This function sets the initial data for all artists and returns them.
        For blitting to work properly, we need to return all artists that will be changing.
        """
        # Return all artists that will change
        return [self._lick_line, self._valve_line, self._speed_line, self._volume_text]

    def _animate(self, frame_num):
        """Update the animation with new data.

        This function is called by FuncAnimation to update the plot.
        It must return all artists that have been modified.

        Args:
            frame_num: The frame number (provided by FuncAnimation)

        Returns:
            List of artists that have been modified
        """
        # Sample new data
        self._sample_data()

        # Update data for all artists
        self._lick_line.set_data(self._timestamps, self._lick_data)
        self._valve_line.set_data(self._timestamps, self._valve_data)
        self._speed_line.set_data(self._timestamps, self._speed_data)

        # Update volume text if changed
        if self._total_volume != self._last_volume:
            self._volume_text.set_text(f"Total Volume: {self._total_volume:.2f} μL")
            self._last_volume = self._total_volume

        # Return all artists that changed
        return [self._lick_line, self._valve_line, self._speed_line, self._volume_text]

    def is_initialized(self) -> bool:
        """Check if visualizer is initialized."""
        return self._initialized

    def update(self) -> None:
        """Update visualization.

        This method doesn't need to do anything with animation active,
        but is kept for API compatibility.
        """
        if not self._initialized:
            self.initialize()

        # Delays execution to update the figure
        plt.pause(0.001)

    def close(self) -> None:
        """Close visualization and clean up resources."""
        if self._initialized:
            # Stop the animation
            if self._animation is not None:
                self._animation.event_source.stop()

            # Close the figure
            plt.close(self._figure)

            # Reset object references
            self._figure = None
            self._lick_axis = None
            self._valve_axis = None
            self._speed_axis = None
            self._animation = None
            self._initialized = False

    def _update_plots(self) -> None:
        """Update all plots with current data while maintaining the shared x-axis."""
        # Clear all axes
        self._lick_axis.clear()
        self._valve_axis.clear()
        self._speed_axis.clear()

        # Update individual plots
        self._update_lick_plot()
        self._update_valve_plot()
        self._update_speed_plot()

        # Set the same x-axis limits for all plots (due to sharex=True, this will apply to all)
        self._speed_axis.set_xlim(self._minimum_time-1, 1)

        # Only show x-axis label and ticks on the bottom plot to avoid redundancy
        plt.setp(self._lick_axis.get_xticklabels(), visible=False)
        plt.setp(self._valve_axis.get_xticklabels(), visible=False)

        # Align y-axis labels to ensure they're all aligned with each other
        self._figure.align_ylabels([self._lick_axis, self._valve_axis, self._speed_axis])

        # Process any pending events
        self._figure.canvas.draw_idle()
        self._figure.canvas.flush_events()

    def _update_lick_plot(self) -> None:
        """Updates the lick sensor plot with new data."""
        # Plots lick ADC units as discrete steps
        self._lick_axis.plot(
            self._timestamps,
            self._lick_data,
            drawstyle="steps-post",
            alpha=1.0,
            linewidth=2,
            color=_plt_palette("red"),
            linestyle="solid",
        )

        # Plots the lick detection threshold line
        self._lick_axis.axhline(
            y=self._lick_threshold,
            color=_plt_palette("black"),
            linestyle="dashed",
            linewidth=1.5,
            alpha=0.7,
            label="Lick Threshold",
        )

        # Configures plot layout - keep title and y-axis settings
        self._lick_axis.set_title("Lick Sensor State", fontdict=_fontdict_title)
        self._lick_axis.set_ylim(-100, 4200)
        self._lick_axis.set_ylabel("Voltage (ADC units)", fontdict=_fontdict_axis_label)

        # No x-axis label on top plot (it's shared, only shown on bottom plot)
        self._lick_axis.set_xlabel("")

        # Optimizes tick locations for y-axis only (x-axis is shared)
        self._lick_axis.yaxis.set_major_locator(MaxNLocator(nbins="auto", integer=True))

    def _update_valve_plot(self) -> None:
        """Updates the reward valve plot with new data."""
        # Plots valve state as discrete steps
        self._valve_axis.plot(
            self._timestamps,
            self._valve_data,
            drawstyle="steps-post",
            alpha=1.0,
            linewidth=2,
            color=_plt_palette("blue"),
            linestyle="solid",
        )

        # Configures plot layout - keep title and y-axis settings
        self._valve_axis.set_title("Reward Valve State", fontdict=_fontdict_title)
        self._valve_axis.set_ylim(-0.05, 1.05)
        self._valve_axis.set_ylabel("Valve State", fontdict=_fontdict_axis_label)

        # No x-axis label on middle plot (it's shared, only shown on bottom plot)
        self._valve_axis.set_xlabel("")

        # Add text showing total water volume
        self._valve_axis.text(
            0.02,  # Slightly increased from edge (2% from left)
            0.75,  # Lower position (75% from bottom) to avoid y-axis top
            f"Total Volume: {self._total_volume:.2f} μL",
            transform=self._valve_axis.transAxes,
            fontdict=_fontdict_legend,
            bbox=dict(facecolor="white", alpha=0.7, pad=3.0, boxstyle="round,pad=0.3"),
            horizontalalignment='left',  # Ensure left alignment
            verticalalignment='top',  # Align to top of text
        )

        # Set y-tick formatting for the valve state (open/closed)
        self._valve_axis.yaxis.set_major_locator(plt.FixedLocator([0, 1]))
        self._valve_axis.yaxis.set_major_formatter(plt.FixedFormatter(["Closed", "Open"]))

    def _update_speed_plot(self) -> None:
        """Update the movement plot."""
        # Plots the average running speed
        self._speed_axis.plot(
            self._timestamps,
            self._speed_data,
            alpha=1.0,
            linewidth=2,
            color=_plt_palette("green"),
            linestyle="solid",
        )

        # Configures plot layout - keep title and y-axis settings
        self._speed_axis.set_title("Average Running Speed", fontdict=_fontdict_title)
        self._speed_axis.set_ylim(-2, 32)  # 0 cm/s to 30 cm/s
        self._speed_axis.set_ylabel("Running speed (cm/s)", fontdict=_fontdict_axis_label)

        # Show x-axis label only on bottom plot (since it's shared with all plots)
        self._speed_axis.set_xlabel("Time (ms)", fontdict=_fontdict_axis_label)

        # Optimizes tick locations for y-axis only (x-axis is shared)
        self._speed_axis.yaxis.set_major_locator(MaxNLocator(nbins="auto", integer=False))

        # Set x-axis tick locations for all plots (this will affect all plots due to sharex=True)
        self._speed_axis.xaxis.set_major_locator(MaxNLocator(nbins="auto", integer=True))

    def _sample_data(self) -> None:
        """Sample new data from trackers and update the data arrays."""
        # Rolls arrays by one position to the left, so the first element becomes last
        self._valve_data = np.roll(self._valve_data, shift=-1)
        self._lick_data = np.roll(self._lick_data, shift=-1)
        self._speed_data = np.roll(self._speed_data, shift=-1)

        # Replace the last element with new data
        self._valve_data[-1] = self._valve_tracker.read_data(index=0, convert_output=False)
        self._lick_data[-1] = self._lick_tracker.read_data(index=0, convert_output=False)
        self._speed_data[-1] = self._speed_tracker.read_data(index=0, convert_output=False)

        # Update total volume
        self._total_volume = self._valve_tracker.read_data(index=1, convert_output=False)


# Example usage
if __name__ == "__main__":

    console.enable()

    console.echo("Starting BehaviorVisualizer simulation...")

    # Create shared memory arrays for testing
    lick = SharedMemoryArray.create_array(
        name="fake_lick_data", prototype=np.zeros(shape=2, dtype=np.uint16), exist_ok=True
    )
    valve = SharedMemoryArray.create_array(
        name="fake_valve_data", prototype=np.zeros(shape=2, dtype=np.float64), exist_ok=True
    )
    speed = SharedMemoryArray.create_array(
        name="fake_speed_data", prototype=np.zeros(shape=1, dtype=np.float64), exist_ok=True
    )

    # Create and initialize the visualizer
    visualizer = BehaviorVisualizer(
        lick_tracker=lick,
        valve_tracker=valve,
        speed_tracker=speed,
        time_window=10,  # 10 seconds of data
    )
    visualizer.initialize()

    # Generate test data
    samples = 2000

    # Generate random data with some patterns
    time_points = np.linspace(0, 20 * np.pi, samples)
    licks = (np.sin(time_points / 2) > 0.7).astype(int)  # Occasional high spikes
    valves = (np.sin(time_points / 5) > 0.8).astype(int)  # Occasional valve openings
    speeds = 10 + 5 * np.sin(time_points / 10) + np.random.normal(0, 1, samples)  # Sinusoidal movement with noise

    # Calculate cumulative volumes when valve is open
    volumes = np.zeros_like(valves, dtype=float)
    volume_per_activation = 2.5
    for i in range(len(valves)):
        if valves[i] == 1:
            volumes[i] = volume_per_activation
        if i > 0:
            volumes[i] += volumes[i - 1]

    # Main simulation loop - this would be your experiment/application loop
    timer = PrecisionTimer("ms")
    for num in range(samples):
        # Update shared memory with new data
        lick.write_data(index=0, data=licks[num])
        valve.write_data(index=0, data=valves[num])
        valve.write_data(index=1, data=volumes[num])
        speed.write_data(index=0, data=speeds[num])

        # Update visualization (non-blocking)
        visualizer.update()

        timer.delay_noblock(30)

        # Print progress occasionally
        if num % 200 == 0:
            console.echo(f"Processed {num} samples", LogLevel.SUCCESS)

    print("Simulation complete")

    lick.disconnect()
    lick.destroy()
    valve.disconnect()
    valve.destroy()
    speed.disconnect()
    speed.destroy()

    visualizer.close()
