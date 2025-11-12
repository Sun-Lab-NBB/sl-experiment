"""This module provides the interfaces for Zaber devices used in the Mesoscope-VR data acquisition system."""

from typing import Any
from dataclasses import field, dataclass

from crc import Calculator, Configuration
from tabulate import tabulate
from zaber_motion import Tools, Units
from ataraxis_time import PrecisionTimer
from zaber_motion.ascii import Axis, Device, Connection, SettingConstants
from ataraxis_base_utilities import console, LogLevel


@dataclass
class _ZaberAxisData:
    """Stores the identification data about an axis of a Zaber device."""
    axis_id: int
    axis_label: str


@dataclass
class _ZaberDeviceData:
    """Stores the identification data about a Zaber device."""
    device_number: int
    device_id: int
    label: str
    name: str
    axes: list[_ZaberAxisData] = field(default_factory=list)


@dataclass
class _ZaberPortData:
    """Stores the identification data for all Zaber devices connected to a serial port."""
    port_name: str
    devices: list[_ZaberDeviceData] = field(default_factory=list)

    @property
    def has_devices(self) -> bool:
        """Returns True if any devices are connected to this port."""
        return len(self.devices) > 0


def _attempt_connection(port: str) -> list[_ZaberDeviceData]:
    """Checks the specified USB port for Zaber devices and parses identification data for any discovered device.

    Args:
        port: The name of the USB port to scan for Zaber devices.

    Returns:
        A list of _ZaberDeviceData instances, one for each discovered device or an empty list if none are discovered.
    """
    # Uses 'with' to automatically close the connection at the end of the runtime. If the port is used by a Zaber
    # device, this statement opens the connection. Otherwise, the statement raises an exception.
    with Connection.open_serial_port(port_name=port, direct=False) as connection:
        # Detects all devices connected to the port
        devices = connection.detect_devices()

        # Parses device information into _ZaberDeviceData instances
        device_list = []
        for num, device in enumerate(devices):
            axes = [
                _ZaberAxisData(
                    axis_id=axis_num,
                    axis_label=device.get_axis(axis_number=axis_num).label or "Not Used"
                )
                for axis_num in range(1, device.axis_count + 1)
            ]

            device_info = _ZaberDeviceData(
                device_number=num + 1,
                device_id=device.device_id,
                label=device.label,
                name=device.name,
                axes=axes
            )
            device_list.append(device_info)

        return device_list


def _scan_active_ports() -> list[_ZaberPortData]:
    """Scans all available serial ports for Zaber devices and parses their identification data.

    Returns:
        A list of _ZaberPortData objects, one for each scanned port.
    """
    port_info_list = []

    # Gets the list of serial ports active for the current platform and scans each to determine if any zaber devices
    # are connected to that port.
    for port in Tools.list_serial_ports():
        try:
            devices = _attempt_connection(port=port)
            port_info = _ZaberPortData(port_name=port, devices=devices)
        except Exception as e:
            # Logs connection errors at debug level and creates empty _ZaberPortData instances.
            console.echo(f"Error connecting to port {port}: {e}.", level=LogLevel.DEBUG)
            port_info = _ZaberPortData(port_name=port, devices=[])

        port_info_list.append(port_info)

    return port_info_list


def _format_device_info(port_info_list: list[_ZaberPortData]) -> str:
    """Formats the device and axis ID information discovered during port scanning as a table before displaying it to
     the user.

    Args:
        port_info_list: A list of _ZaberPortData instances containing device and axis information for each scanned port.

    Returns:
        A string containing the formatted device and axis ID information as a table.
    """
    # Pre-creates the list used to generate the formatted table
    table_data = []

    # Format the port scanning data as a table
    for port_info in port_info_list:
        if not port_info.has_devices:
            table_data.append([port_info.port_name, "No Devices", "", "", "", "", ""])
        else:
            for device in port_info.devices:
                device_row = [
                    port_info.port_name,
                    str(device.device_number),
                    str(device.device_id),
                    device.label,
                    device.name
                ]
                for axis in device.axes:
                    axis_row = device_row + [str(axis.axis_id), axis.axis_label]
                    table_data.append(axis_row)
                    device_row = [""] * 5
        table_data.append([""] * 7)  # Adds an empty row to separate port sections

    # Formats the table and returns it to the caller
    return tabulate(
        table_data,
        headers=["Port", "Device Num", "ID", "Label", "Name", "Axis ID", "Axis Label"],
        tablefmt="grid",
        stralign="center",
    )


def discover_zaber_devices() -> None:
    """Scans all available serial ports and displays information about connected Zaber devices.

    Note:
        Connection errors encountered during scanning are logged at DEBUG level and do not interrupt
        the discovery process. Ports that cannot be connected are listed as having "No Devices".
    """
    port_info_list = _scan_active_ports()  # Scans all active ports
    formatted_info = _format_device_info(port_info_list)  # Formats the information so that it displays nicely

    # Prints the formatted table. Since the data uses external formatting (tabulate), it does not need to be printed
    # with the console.
    print("Device and Axis Information:")
    print(formatted_info)


class CRCCalculator:
    """A CRC32-XFER checksum calculator that works with raw bytes or pythonic strings.

    This utility class exposes methods that generate CRC checksum labels and bytes objects, which are primarily used by
    Zaber binding classes to verify that Zaber devices have been configured to work with the binding interface exposed
    by this library.

    Attributes:
        _calculator: Stores the configured Calculator class object used to calculate the checksums.
    """

    def __init__(self) -> None:
        # Specializes and instantiates the CRC checksum calculator
        config = Configuration(
            width=32,
            polynomial=0x000000AF,
            init_value=0x00000000,
            final_xor_value=0x00000000,
            reverse_input=False,
            reverse_output=False,
        )
        self._calculator = Calculator(config)

    def string_checksum(self, string: str) -> int:
        """Calculates the CRC32-XFER checksum for the input string.

        The input strings are first converted to bytes using ASCII protocol. The checksum is then calculated on the
        resultant bytes-object.

        Args:
            string: The string for which to calculate the CRC checksum.

        Returns:
            The integer CRC32-XFER checksum.
        """
        return self._calculator.checksum(data=bytes(string, "ASCII"))


@dataclass(frozen=True)
class _ZaberSettings:
    """Maps Zaber setting codes to descriptive names.

    This class functions as an additional abstraction layer that simplifies working with Zaber device and axis setting
    interface.

    Notes:
        This class only lists the settings used by the classes of this module and does not cover all available Zaber
        settings.
    """
    axis_maximum_limit: str = SettingConstants.LIMIT_MAX
    """The maximum absolute position the motor is allowed to reach, relative to the home position."""
    axis_minimum_limit: str = SettingConstants.LIMIT_MIN
    """The minimum absolute position the motor is allowed to reach, relative to the home position."""
    axis_inversion: str = SettingConstants.DRIVER_DIR
    """A boolean flag that determines whether the motor is inverted (True) or not (False). From the perspective of the 
    motor, this determines whether moving towards home constitutes 'negative' displacement (default) or 'positive' 
    displacement."""
    axis_position: str = SettingConstants.POS
    """The current absolute position of the motor relative to its home position."""
    device_code: str = SettingConstants.USER_DATA_0
    """The CRC32 checksum that should match the checksum of the device's label. This value is used to confirm that the 
    device has been configured to work with the bindings exposed from this library. Uses USER_DATA 0 variable."""
    device_shutdown_flag: str = SettingConstants.USER_DATA_1
    """The boolean flag that tracks whether the device has been properly shut down during the previous runtime. This 
    acts as a secondary verification mechanism to ensure that the device has been set to the correct parking position 
    before connection cycles. Uses USER_DATA 1 variable."""
    axis_linear_flag: str = SettingConstants.USER_DATA_10
    """The boolean flag that specifies if axis 1 motor is linear or rotary. This indirectly controls how this library 
    interfaces with the motor. Uses USER_DATA 10 variable."""
    axis_park_position: str = SettingConstants.USER_DATA_11
    """The absolute position, in native motor units, where the motor should be moved to before parking and shutting 
    down. This is used to ensure the motor will not collide with any physical boundaries when it is homed after 
    re-connection. Uses USER_DATA 11 variable."""
    axis_calibration_position: str = SettingConstants.USER_DATA_12
    """The absolute position, in native motor units, where the motor should be moved for the water valve calibration 
    procedure. This position is optimized for collecting a large volume of water that will be dispensed through the 
    valve during calibration. Uses USER_DATA 12 variable.
    """
    axis_mount_position: str = SettingConstants.USER_DATA_13
    """The absolute position, in native motor units, where the motor should be moved before mounting the animal onto 
    the VR rig. This is a fallback position used for animals that do not have a calibrated HeadBar and LickPort 
    position to restore between sessions. For most animals, this set of positions will only be used once, during the 
    first training session.
    """


@dataclass(frozen=True)
class _ZaberUnits:
    """Exposes methods for selecting appropriate Zaber units used when communicating with the motor, based on the
    selected motor type and colloquial unit family.

    This class is primarily designed to de-couple colloquial unit names used by our API from the Zaber-defined unit
    names, which is critical for reading and writing hardware settings and when issuing certain commands. To do so,
    after the initial configuration, use class properties to retrieve the necessary units (e.g: for displacement,
    velocity, or acceleration).
    """

    # This dictionary conditionally maps Zaber units to colloquial names, factoring in the type of the motor.
    zaber_units_conversion: dict[str, Any] = field(
        default_factory=lambda: {
            "degrees": {
                "acceleration": Units.ANGULAR_ACCELERATION_DEGREES_PER_SECOND_SQUARED,
                "velocity": Units.ANGULAR_VELOCITY_DEGREES_PER_SECOND,
                "length": Units.ANGLE_DEGREES,
            },
            "millimeters": {
                "acceleration": Units.ACCELERATION_MILLIMETRES_PER_SECOND_SQUARED,
                "velocity": Units.VELOCITY_MILLIMETRES_PER_SECOND,
                "length": Units.LENGTH_MILLIMETRES,
            },
        },
    )
    """The dictionary that maps colloquial unit names to Zaber unit classes."""
    unit_type: str = "millimeters"
    """Tracks the 'family' of the units (e.g: millimeters) being used. Currently, this class only supports two 
    families of units: millimeters and degrees.
    """

    @property
    def displacement_units(self) -> Units:
        """Returns the Units class instance used to work with displacement (length) data."""
        return self.zaber_units_conversion[self.unit_type]["length"]  

    @property
    def acceleration_units(self) -> Units:
        """Returns the Units class instance used to work with acceleration data.

        Note, all acceleration units are given in units / seconds^2.
        """
        return self.zaber_units_conversion[self.unit_type]["acceleration"]  

    @property
    def velocity_units(self) -> Units:
        """Returns the Units class instance used to work with velocity (speed) data.

        Note, all velocity units are given in units / seconds.
        """
        return self.zaber_units_conversion[self.unit_type]["velocity"]  


class ZaberAxis:
    """Interfaces with a Zaber axis (motor).

    This class is the lowest member of the tri-class hierarchy used to control Zaber motors during runtime.

    Notes:
        This class uses 'millimeters' for linear motors and 'degrees' for rotary motors. These units were chosen due to
        achieving the best balance between precision and ease of use for the experimenters in the lab.

    Args:
        motor: Axis class instance that controls the hardware of the motor. This class should be instantiated
            automatically by the ZaberDevice class that manages this ZaberAxis instance.

    Attributes:
        _motor: Stores the Axis class instance that physically controls the motor hardware through Zaber ASCII protocol.
        _name: Stores the user-defined label (name) of the axis.
        _units: stores a ZaberUnits instance used to convert from colloquial unit names used in binding code to
            Zaber-specific Unit classes used during communication with the axis.
        _linear: The boolean flag that determines if the managed motor is driving a linear or a rotary axis. This flag
            determines the units used by the motor (millimeters or degrees).
        _park_position: The absolute position relative to the home sensor position, in native motor units, the motor
            should be parked at before shutting the axis down. This is used to position the motor in a way that is
            guaranteed to successfully home without colliding with surrounding objects after powering-up. This is
            especially relevant for rotary than linear axes.
        _valve_position: The absolute position relative to the home sensor position, in native motor units, the motor
            should be moved to before water reward valve calibration. Since the space inside the Mesoscope-VR rig
            is constrained, it is helpful to orient the headbar and lickport motors in a way that provides easy access
            to the lickport tube. These positions are stored in the non-volatile memory and are used similar to how the
            park position is used.
        _mount_position: The absolute position relative to the home sensor position, in native motor units, the motor
            should be moved to before mounting a naive animal onto the VR rig. This position is used to provide
            experimenters with more working room around the rig and ensure the animal's comfort as it is mounted onto
            the rig. This position is a fallback used when the animal does not have a better, custom-calibrated position
            available. Usually, this would only be the case when the animal is mounted onto the rig for the very first
            time.
        _max_limit: The maximum absolute position relative to the home sensor position, in native motor units,
            the motor hardware can reach.
        _min_limit: Same as the _hardware_max_limit, but specifies the minimum absolute position relative to
            home sensor position, in native motor units, the motor hardware can reach.
        _shutdown_flag: Tracks whether the axis has been shut down. Primarily, this is used to prevent the __del__()
            method from shutting down an already shut axis.
        _timer: A PrecisionTimer class instance that is used to ensure that communication with the motor is carried out
            at a pace that does not overwhelm the connection interface with too many successive calls.

    Raises:
        TypeError: If motor is not an Axis class instance.
        ValueError: If any motor parameter is read from the non-volatile memory is outside the expected range of
            values.
    """

    def __init__(self, motor: Axis) -> None:
        # Only works with Zaber Axis classes
        if not isinstance(motor, Axis):
            message = (
                f"Invalid 'motor' argument type encountered when instantiating ZaberAxis class instance. "
                f"Expected a {type(Axis).__name__}, but encountered {motor} of type {type(motor).__name__}."
            )
            console.error(message=message, error=TypeError)

        # Currently, we only support the Zaber configuration used in our lab, where each controller (device) manages
        # a single axis (motor). Therefore, this check verifies that the input axis (motor) class has the expected
        # axis number of 1. Note, this check is somewhat redundant, as a similar check is performed at the Device level.
        if motor.axis_number != 1:
            message = (
                f"Unexpected value encountered when checking the axis number of the managed motor. Currently, "
                f"ZaberAxis instances only work with devices (controllers) that manage a single Axis (motor), expected "
                f"to have '1' as the axis number. Instead, the axis managed by this instance has the number "
                f"{motor.axis_number}, which indicates that its parent controller manages multiple axes."
            )
            console.error(message=message, error=ValueError)

        # Parses hardcoded information stored in non-volatile controller and device memory:
        self._motor: Axis = motor
        self._name: str = motor.label
        self._linear: bool = bool(self._motor.device.settings.get(setting=_ZaberSettings.axis_linear_flag))
        self._park_position: int = int(self._motor.device.settings.get(setting=_ZaberSettings.axis_park_position))
        self._valve_position: int = int(
            self._motor.device.settings.get(setting=_ZaberSettings.axis_calibration_position)
        )
        self._mount_position: int = int(self._motor.device.settings.get(setting=_ZaberSettings.axis_mount_position))
        self._max_limit: float = self._motor.settings.get(setting=_ZaberSettings.axis_maximum_limit)
        self._min_limit: float = self._motor.settings.get(setting=_ZaberSettings.axis_minimum_limit)

        # Initializes a ZaberUnits instance using the appropriate unit type (depends on motor type).
        self._units: _ZaberUnits
        if self._linear:
            # noinspection PyArgumentList
            self._units = _ZaberUnits(unit_type="millimeters")
        else:
            # noinspection PyArgumentList
            self._units = _ZaberUnits(unit_type="degrees")

        # Verifies that the parking position of the axis is within the hardware-defined motion limits.
        if self._park_position < self._min_limit or self._park_position > self._max_limit:
            message = (
                f"Invalid park_position hardware parameter value encountered when initializing ZaberAxis class for "
                f"{self._name} axis of the Device {self._motor.device.label}. Expected a value between "
                f"{self._min_limit} and {self._max_limit}, but read {self._park_position}."
            )
            console.error(message=message, error=ValueError)

        # Same as above, but for the valve calibration position
        if self._valve_position < self._min_limit or self._valve_position > self._max_limit:
            message = (
                f"Invalid valve calibration position hardware parameter value encountered when initializing ZaberAxis "
                f"class for {self._name} axis of the Device {self._motor.device.label}. Expected a value between "
                f"{self._min_limit} and {self._max_limit}, but read {self._park_position}."
            )
            console.error(message=message, error=ValueError)
        # Same as above, but for the mount position
        if self._mount_position < self._min_limit or self._mount_position > self._max_limit:
            message = (
                f"Invalid mount position hardware parameter value encountered when initializing ZaberAxis "
                f"class for {self._name} axis of the Device {self._motor.device.label}. Expected a value between "
                f"{self._min_limit} and {self._max_limit}, but read {self._park_position}."
            )
            console.error(message=message, error=ValueError)

        # Initializes a timer to ensure the class cannot issue commands fast enough to overwhelm the motor communication
        # interface.
        self._timer = PrecisionTimer(precision="ms")

        # The class requires shutdown after it has been fully initialized.
        self._shutdown_flag: bool = False

    def __repr__(self) -> str:
        """Constructs and returns a string that represents the class instance."""
        # Generates class representation
        representation_string: str = (
            f"ZaberAxis(name={self._name}, units={self._units.unit_type}, inversion={self.inversion}, "
            f"linear={self._linear}, homed={self.is_homed}, parked={self.is_parked}, busy={self.is_busy}, "
            f"position={self.get_position(native=False)}) {self._units.unit_type}"
        )
        return representation_string

    def _ensure_call_padding(self) -> None:
        """This method should be used before each call to motor hardware to ensure it is sufficiently separated
        from other calls to prevent overwhelming the serial connection.

        This method is statically configured to prevent further commands from being issued for the following 10
        milliseconds, which is appropriate for the default Zaber communication baudrate of 115,200.
        """
        while self._timer.elapsed < 10:
            # This design is chosen over delay() to allow instantaneous escapes if this method is called when the delay
            # has already expired
            pass

    def _reset_pad_timer(self) -> None:
        """Resets the PrecisionTimer instance used to enforce a static delay between motor hardware calls.

        This method should be used after each motor hardware call command to reset the timer in preparation for the
        next call (to exclude the time spent on the request-response sequence of the call from the padding
        calculation). It is designed to work together with the _ensure_call_padding method.
        """
        self._timer.reset()

    def get_position(self, native: bool = False) -> float:
        """Returns the current absolute position of the motor relative to the home position.

        Args:
            native: Determines if the returned value should use native motor units (true) or metric units (false). For
            linear axes, the metric units are millimeters. For rotary axes, the metric units are degrees.
        """
        self._ensure_call_padding()
        position: float
        if not native:
            position = self._motor.get_position(unit=self._units.displacement_units)
        else:
            position = self._motor.get_position()  # Defaults to native units
        self._reset_pad_timer()
        return position

    @property
    def is_homed(self) -> bool:
        """Returns True if the motor has a motion reference point (has been homed)."""
        self._ensure_call_padding()
        homed: bool = self._motor.is_homed()
        self._reset_pad_timer()
        return homed

    @property
    def is_parked(self) -> bool:
        """Returns True if the motor is parked."""
        self._ensure_call_padding()
        parked: bool = self._motor.is_parked()
        self._reset_pad_timer()
        return parked

    @property
    def is_busy(self) -> bool:
        """Returns True if the motor is currently executing a motor command (is moving)."""
        self._ensure_call_padding()
        is_busy: bool = self._motor.is_busy()
        self._reset_pad_timer()
        return is_busy

    @property
    def name(self) -> str:
        """Returns the user-defined string-name of the motor axis, e.g.: 'Pitch_Axis'."""
        return self._name

    @property
    def inversion(self) -> bool:
        """Returns the current value of the motor hardware inversion flag.

        Generally, this determines which direction of movement brings the motor towards its home sensor position.
        """
        self._ensure_call_padding()
        inverted: bool = bool(self._motor.settings.get(setting=_ZaberSettings.axis_inversion))
        self._reset_pad_timer()
        return inverted

    @property
    def maximum_limit(self) -> float:
        """Returns the maximum absolute position, relative to the home sensor position, the motor can be moved to.

        It is assumed that the home sensor position is always defined as 0. The returned position is in
        millimeters for linear axes and degrees for rotary axes.
        """
        return self._max_limit

    @property
    def minimum_limit(self) -> float:
        """Returns the minimum absolute position relative to the home sensor position the motor can be moved to.

        It is assumed that the home sensor position is always defined as 0. The returned position is in
        millimeters for linear axes and degrees for rotary axes.
        """
        return self._min_limit

    @property
    def park_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved before it is parked.

        This position is applied to the motor before parking to promote a safe homing procedure once the motor is
        unparked. Parking the motor in a predetermined position avoids colliding with other objects in the environment
        during homing and provides a starting point for calibrating the motor's position for new animals.
        """
        return self._park_position

    @property
    def valve_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved before calibrating
        the water reward valve of the Mesoscope-VR system.

        Applying this position to the motor orients the headbar and lickport system in a way that provides easy access
        to the components of the water delivery system. In turn, this simplifies calibrating, flushing, and filling the
        system with water.
        """
        return self._valve_position

    @property
    def mount_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved before mounting
        the animal onto the VR rig.

        Applying this position to the motor orients the headbar and lickport system in a way that makes it easier to
        mount the animal, while also providing the animal with a comfortable position inside the VR rig.
        """
        return self._mount_position

    def home(self) -> None:
        """Homes the motor by moving it towards the home sensor position until it triggers the sensor.

        This method establishes a stable reference point used to execute all further motion commands.

        Notes:
            This class as a whole makes a considerable effort to avoid having to re-home the device by parking it before
            expected power shutdowns. That said, it is usually a good practice to home all devices after they had
            been idle for a prolonged period of time.

            The method initializes the homing procedure but does not block until it is over. As such, it is likely
            that the motor will still be moving when this method returns. This feature is designed to support homing
            multiple axes in parallel.
        """
        # A parked motor cannot be homed until it is unparked. As a safety measure, this command does NOT automatically
        # override the parking state.
        if self.is_parked:
            return

        # In line with the logic of handling conflicting motion commands, the motor is not allowed to execute a home
        # command unless it is idle.
        if self.is_busy:
            return

        # If the motor has already been homed, first moves it to the parking position and then repeats the homing
        # procedure. The reason behind this implementation instead of the default 'home' command is to handle a case
        # unique to rotary axis that has been artificially limited to a certain motion range. In our case, this is the
        # headbar yaw axis, which can collide with a physical limiter if it is homed when it is 'below' home sensor.
        if self.is_homed:
            self._ensure_call_padding()
            self._motor.move_absolute(position=self._park_position, wait_until_idle=False)
            self._reset_pad_timer()

        # Moves the motor towards the home sensor until it triggers the limit switch. This is the default 'home' action
        # intended to ONLY be triggered from the default parking position.
        self._ensure_call_padding()
        self._motor.home(wait_until_idle=False)
        self._reset_pad_timer()

    def move(self, amount: float, absolute: bool, native: bool = False) -> None:
        """Moves the motor to the requested position.

        Depending on the type of the motor and the native flag, the motion is either performed in millimeters (for
        linear axes), degrees (for rotary axes), or native units (for both types). Relative values are first converted
        to absolute values before being issued to the motor. The method contains internal mechanisms that prevent
        movement outside the hardware-defined motion range.

        Notes:
            This method executes movement in a non-blocking fashion. As such, the method will most likely return
            before the motor finishes the move command. This behavior is designed to enable partially overlapping
            concurrent operation of multiple motors.

        Args:
            amount: The amount to move the motor by. Depending on the value of the 'absolute' argument, this
                can either be the exact position to move the motor to or the number of displacement units to move the
                motor by.
            absolute: A boolean flag that determines whether the input displacement amount is the absolute position to
                move the motor to (relative to home sensor position) or a displacement value to move the motor by
                (relative to its current absolute position).
            native: A boolean flag that determines whether the input amount is given in metric displacement units of the
                motor or in native motor units.
        """
        # If the motor is already executing a different command, it has to be stopped or allowed to finish the command
        # before executing a new command. This contradicts the default Zaber behavior of replacing the active motor
        # command, but this way of handling conflicting commands promotes safety and was therefore considered
        # preferable.
        if self.is_busy:
            return

        # Due to the way movement position resolution is implemented below, the motor cannot move reliably unless it
        # has been homed.
        if not self.is_homed:
            return

        # Parking prevents the motor from moving at all, so a parked motor cannot be moved either.
        if self.is_parked:
            return

        # Converts the displacement amount into native units (and, together with the step below), converts it to the
        # target absolute position to move the motor to.
        if not native:
            self._ensure_call_padding()
            position: float = self._motor.settings.convert_to_native_units(
                setting=_ZaberSettings.axis_position, value=amount, unit=self._units.displacement_units
            )
            self._reset_pad_timer()
        else:
            position = amount

        # If the input amount uses relative referencing, converts it to absolute by getting the current position and
        # adjusting it by the requested displacement amount. This essentially switches all motion commands to absolute,
        # which is a safer option compared to relative motion.
        if not absolute:
            self._ensure_call_padding()
            position += self._motor.get_position()
            self._reset_pad_timer()

        # Ensures that the position to move the motor to is within the motor software limits.
        if position < self._min_limit or position > self._max_limit:
            return

        # Initiates the movement of the motor
        self._ensure_call_padding()
        self._motor.move_absolute(position=position, wait_until_idle=False)
        self._reset_pad_timer()

    def stop(self) -> None:
        """Decelerates and stops the motor.

        Unlike most other motion commands, this command can be executed to interrupt any other already running motor
        command. This method is especially relevant during emergencies, as it has the potential to immediately stop
        the motor.

        Notes:
            Calling this method once instructs the motor to decelerate and stop. Calling this method twice in a row
            instructs the motor to stop immediately (without deceleration). Using this method for immediate shutdowns
            can have negative consequences for the motor and / or the load of the motor and other motors (axes) of the
            device.

            This command does not block until the motor stops to allow stopping multiple motors (axes) in rapid
            succession.
        """
        # Note, this is the only command that does not have a padding timer check. This design pattern is to allow
        # unhindered runtime for this method to support the cases where it is used as an emergency measure.
        self._motor.stop(wait_until_idle=False)
        self._reset_pad_timer()

    def park(self) -> None:
        """Parks the motor, which makes it unresponsive to motor commands and stores current absolute motor position in
        non-volatile memory.

        This method is mostly used to avoid re-homing the device after power cycling, as parking ensures the reference
        point for the motor is maintained in non-volatile memory. Additionally, parking is used to lock the motor
        in place as an additional safety measure.
        """
        # The motor has to be idle to be parked.
        if self.is_busy:
            return

        self._ensure_call_padding()
        self._motor.park()
        self._reset_pad_timer()

    def unpark(self) -> None:
        """Unparks a parked motor, which allows the motor to accept and execute motion commands."""
        if self._motor.is_parked():
            self._ensure_call_padding()
            self._motor.unpark()
            self._reset_pad_timer()

    def shutdown(self) -> None:
        """Prepares the motor for shutting down by moving the motor to a hardware-defined shutdown parking position.

        This method has to be called at the end of each class runtime to ensure the class can be reused without manual
        intervention later.

        Notes:
            This method contains the guards that prevent it from being executed if the motor has already been shut down.
        """
        # If the shutdown flag indicates that the motor has already been shut, aborts method runtime and returns None
        if self._shutdown_flag:
            return

        # If the motor is moving, stops the motor and waits until it is idle
        if self.is_busy:
            self._motor.stop(wait_until_idle=True)

        self.park()  # Parks the motor before shutdown
        self._shutdown_flag = True  # Sets the shutdown flag to True to indicate that the motor has been shut down

    def emergency_shutdown(self) -> None:
        """Stops and parks the motor.

        This method purposefully avoids moving the motor to the park position before shutdown. It is designed to be
        called in the case of emergency, when the managing runtime crashes. Users should use the default 'shutdown'
        method.
        """
        if self._shutdown_flag is not None and not self._shutdown_flag and not self.is_parked:
            # Issues the stop command
            if self.is_busy:
                self.stop()

            # Waits for the motor to seize movement
            while self._motor.is_busy():
                continue

            # Parks the motor
            self.park()


class ZaberDevice:
    """Manages a single Zaber device (controller) and all of its axes (motors).

    This class represents a single Zaber controller device, which contains independent CPU and volatile / non-volatile
    addressable memory. Depending on the model, a single device can control between one and four axes (motor drivers).
    Each device has a fairly high degree of closed-loop autonomy and, as such, is treated as a standalone external
    system.

    Notes:
        This class is explicitly designed to work with devices that manage a single axis (motor). It will raise errors
        if it is initialized for a controller with more than a single axis.

    Args:
        device: The Device class instance that manages the controller. This should be automatically instantiated
            by the ZaberConnection class that discovers and binds the device.

    Attributes:
        _device: The Device class instance that handles all low-level manipulations necessary to control the device.
        _id: The unique numeric ID of the device. Typically, this is hardcoded by the manufacturer.
        _name: The name of the device, typically written to hardware non-volatile memory by the manufacturer
            (e.g.: 'CTX102').
        _label: The user-defined name of the device. This name is assigned during initial configuration, and for any
            well-configured controller (device) the USER_DATA_0 non-volatile variable should always store the
            CRC32-XFER checksum of this label (using ASCII protocol to convert the label to bytes).
        _crc_calculator: An instance of the CRCCalculator() class used to verify the device_code against the
            checksum of the device label.
        _axis: Stores the ZaberAxis class instance used to interface with the motor managed by this Device instance.
        _shutdown_flag: A boolean flag that locally tracks the shutdown status of the device.

    Raises:
        RuntimeError: If the device_code stored in the device's non-volatile memory does not match the CRC32-XFER
            checksum of the device label. Also, if the device shutdown tracker is not set to 1 (if the device has not
            been properly shut down during the previous runtime).
        ValueError: If the device manages more than a single axis (motor).
        TypeError: If any of the initialization argument types do not match the expected types.
    """

    def __init__(self, device: Device) -> None:
        # Ensures arguments are of a valid type
        if not isinstance(device, Device):
            message = (
                f"Invalid 'device' argument type encountered when instantiating ZaberDevice class instance. "
                f"Expected a {type(Device)}, but encountered {device} of type {type(device)}."
            )
            console.error(message=message, error=TypeError)

        # Extracts and records the necessary ID information about the device
        self._device: Device = device
        self._id: int = device.device_id
        self._name: str = device.name
        self._label: str = device.label

        # Ensures that the device is managing a single axis.
        if device.axis_count != 1:
            message = (
                f"Unexpected value encountered when checking the number of axes (motors) managed by the device "
                f"{self._label}. Currently, ZaberDevice instances only work with devices (controllers) that manage a "
                f"single Axis (motor). Instead, the device has {device.axis_count} axes, which indicates that it "
                f"manages multiple motors."
            )
            console.error(message=message, error=ValueError)

        # Initializes the ZaberAxis class to interface with the motor managed by the Device.
        self._axis: ZaberAxis = ZaberAxis(motor=self._device.get_axis(axis_number=1))

        # Creates a CRC32-XFER calculator to confirm the device has been configured to work with Ataraxis binding.
        self._crc_calculator: CRCCalculator = CRCCalculator()

        # Uses the CRC calculator to generate the checksum for the device label string. It is expected that the
        # device_code (USER_DATA_0) non-volatile variable of the device is set to this checksum for any
        # correctly configured device.
        device_check: int = self._crc_calculator.string_checksum(self._label)

        # Verifies that the device has been configured to work with Ataraxis bindings by comparing its device_code
        # with the checksum calculated above.
        device_code: int = int(device.settings.get(setting=_ZaberSettings.device_code))
        if device_code != device_check:
            message = (
                f"Unable to verify that the ZaberDevice instance for {self._label} ({self._name}) device is configured "
                f"to work with ZaberDevice class instance. Based on the device label '{self._label}', expected the "
                f"validation code of {device_check}, but read {device_code}. Make sure the device is configured "
                f"appropriately and re-initialize the class. The default Zaber controller non-volatile memory variable "
                f"used to store this data is USER_DATA_0."
            )
            console.error(message=message, error=RuntimeError)

        # Verifies that the device has been properly shut down during the previous runtime. While this does not
        # prevent all potential issues due to the device being moved while disabled, it rules-out issues due to
        # incorrect shutdown of the previous runtime.
        shutdown_flag: bool = bool(self._device.settings.get(setting=_ZaberSettings.device_shutdown_flag))
        if not shutdown_flag:
            message = (
                f"Unable to initialize ZaberDevice class instance for {self._label} ({self._name}) device, as it was "
                f"not properly shutdown during the previous runtime. Ensure that the device is set (positioned) "
                f"correctly for homing procedure, manually set the value of the shutdown tracker to 1 and reinitialize "
                f"the class. The default Zaber controller non-volatile memory variable used for the tracker is "
                f"USER_DATA_1."
            )
            console.error(message=message, error=RuntimeError)

        # Sets the device shutdown tracker to 0. This tracker is used to detect when a device is not properly shut
        # down, which may have implications for the use of the device, such as the ability to home the device.
        # During the proper shutdown procedure, the tracker is always set to 1, so setting it to 0 now allows
        # detecting cases where the shutdown is not carried out.
        self._device.settings.set(setting=_ZaberSettings.device_shutdown_flag, value=0)
        self._shutdown_flag = False  # Also sets the local shutdown flag

    def __repr__(self) -> str:
        """Constructs and returns a string that represents the class."""
        # Constructs the class representation string
        representation_string = f"ZaberDevice(name='{self.name}', label={self.label})"
        return representation_string

    def shutdown(self) -> None:
        """Shuts down the axis (motor) managed by the device and changes the shutdown tracker non-volatile variable of
        the device to 1.

        Notes:
            This method is intended to be called by the parent ZaberConnection class as part of the disconnect()
            method runtime.
        """
        # Shuts down the managed axis (motor)
        self._axis.shutdown()

        # Sets the shutdown flag to 1 to indicate that the shutdown procedure has been performed.
        self._device.settings.set(setting=_ZaberSettings.device_shutdown_flag, value=1)
        self._shutdown_flag = True  # Also sets the local shutdown flag

    def emergency_shutdown(self) -> None:
        """Stops and parks the managed motor axes, but does not reset the shutdown flag.

        This method is designed to be used exclusively by the __del__ method of the managing ZaberConnection class to
        end the runtime.
        """
        self._axis.emergency_shutdown()

    @property
    def label(self) -> str:
        """Returns the label (user-assigned descriptive name) of the device."""
        return self._label

    @property
    def name(self) -> str:
        """Returns the name (manufacturer-assigned hardware name) of the device."""
        return self._name

    @property
    def id(self) -> int:
        """Returns the unique numeric ID of the device."""
        return self._id

    @property
    def axis_information(self) -> dict[str, str]:
        """Returns a dictionary that provides the basic ID information about the axis controlled by this device."""
        return {"Name": self._axis.name}

    @property
    def axis(self) -> ZaberAxis:
        """Returns the ZaberAxis class reference for the axis (motor) managed by the ZaberDevice instance."""
        return self._axis


class ZaberConnection:
    """Interfaces with a serial USB port and all Zaber devices (controllers) and axes (motors) available through that
    port.

    This class exposes methods for connecting to and disconnecting from all Zaber peripherals that use a given USB
    port. Additionally, the class automates certain procedures, such as setting up and shutting down all associated
    peripherals as part of its connection or disconnection runtimes.

    Notes:
        This class functions as the highest level of the tri-class Zaber binding hierarchy. A single serial connection
        can be used to access multiple Zaber devices (motor controllers), with each device managing a single axis
        (motor).

        This class does not automatically initialize the connection with the port. Use the connect() method to connect
        to the port managed by this class.

    Args:
        port: The name of the USB port used by this connection instance (eg: COM1, USB0, etc.). Use
            discover_zaber_devices() to determine the USB pots used by Zaber devices.

    Attributes:
        _port: Stores the name of the serial port used by the connection.
        _connection: The Connection class instance is used to physically manage the connection. Initializes to a None
            placeholder until the connection is established via the connect() method.
        _devices: The tuple of ZaberDevice class instances used to interface with Zaber devices available through the
            connected port. Initializes to an empty tuple placeholder.
        _is_connected: The boolean flag that communicates the current connection state.

    Raises:
        TypeError: If the provided 'port' argument type is not a string.
    """

    def __init__(self, port: str):
        if not isinstance(port, str):
            message = (
                f"Invalid 'port' argument type encountered when instantiating ZaberConnection class instance. "
                f"Expected a {type(str).__name__}, but encountered {port} of type {type(port).__name__}."
            )
            console.error(message=message, error=TypeError)

        self._port: str = port
        self._connection: Connection | None = None
        self._devices: tuple[ZaberDevice, ...] = ()
        self._is_connected: bool = False

    def __repr__(self) -> str:
        """Constructs and returns a string that represents the class."""
        # Constructs the class representation string
        repr_string = (
            f"ZaberConnection(port='{self._port}', device_count={self.device_count}, connected={self.is_connected})"
        )
        return repr_string

    def __del__(self) -> None:
        """Ensures that the connection is shut down gracefully whenever the class instance is deleted."""
        if self._connection is not None and self.is_connected:
            # Note, this does NOT execute the full shutdown() procedure. This is intentional, as shutdown necessarily
            # involves moving the motors to the parking position, and this may not be safe in all circumstances.
            # Therefore, the user can only call shutdown manually.
            for device in self._devices:
                device.emergency_shutdown()

            self._connection.close()

    def connect(self) -> None:
        """Opens the serial port and automatically detects and connects to any available Zaber devices (controllers).

        Depending on the input arguments, the method may also raise or print exception messages to inform the user of
        the cause of the runtime failure.

        Raises:
            NoDeviceFoundException: If no compatible Zaber devices are discovered using the target serial port.
        """
        # If the connection is already established, prevents from attempting to re-establish the connection again.
        if self.is_connected:
            return

        # Establishes connection
        self._connection = Connection.open_serial_port(port_name=self._port, direct=False)

        # Sets the connection status to connected
        self._is_connected = True

        # Gets the list of connected Zaber devices.
        devices: list[Device] = self._connection.detect_devices()

        # Packages each discovered Device into a ZaberDevice class instance and builds the internal device list.
        self._devices = tuple([ZaberDevice(device=device) for device in devices])

    def disconnect(self) -> None:
        """Shuts down all controlled Zaber devices and closes the connection.

        Notes:
            Make sure it is safe to park the motor before this method is called. Calling it will move the motor which
            may damage the environment or motors.

        Specifically, loops over each connected device and triggers its shutdown() method to execute the necessary
        pre-disconnection procedures. Then, disconnects from the serial port and clears the device list.
        """
        # Prevents the method from running if the connection is not established.
        if not self.is_connected:
            return

        # Loops over each connected device and triggers the shutdown procedure
        for device in self._devices:
            device.shutdown()

        # Resets the device tuple, closes the connection, and sets the connection tracker to False.
        self._devices = tuple()
        self._is_connected = False
        if self._connection is not None:
            self._connection.close()

    @property
    def is_connected(self) -> bool:
        """Returns True if the class has established connection with the managed serial port."""
        # Actualizes the connection status and returns it to the caller
        if self._connection is not None and self._is_connected:
            try:
                # Tries to detect available devices using the connection. If the connection is broken, this will
                # necessarily fail with an error.
                self._connection.detect_devices()
                self._is_connected = True  # If device check succeeded connection is active
                return True
            except Exception:
                # Otherwise, the connection is broken
                self._is_connected = False
        return False

    @property
    def port(self) -> str:
        """Returns the name of the serial port used by the connection."""
        return self._port

    @property
    def device_information(self) -> dict[int, Any]:
        """Returns a dictionary that provides the basic ID information about all Zaber devices using this connection."""
        return {
            num: {"ID": device.id, "Label": device.label, "Name": device.name}
            for num, device in enumerate(self._devices)
        }

    @property
    def device_count(self) -> int:
        """Returns the number of Zaber devices using this connection."""
        return len(self._devices)

    def get_device(self, index: int = 0) -> ZaberDevice:
        """Returns the ZaberDevice class reference for the device under the requested index.

        Args:
            index: The index of the device class to retrieve. Use the device_information property to find the indices
                of the devices available through this connection. Valid indices start with 0 for the first device and
                cannot exceed the value of the device_count property. Defaults to 0.

        Returns:
            A ZaberDevice class object used to control the requested device.

        Raises:
            TypeError: If the index argument is not of the correct type.
            ValueError: If the input index is outside the valid range of indices, or if this method is called for a
                connection that does not have any associated ZaberDevice class instances.
        """
        if not isinstance(index, int):
            message = (
                f"Invalid 'index' argument type encountered when retrieving ZaberDevice object from ZaberConnection "
                f"class for {self.port} port. Expected a {type(int).__name__}, but encountered {index} of type "
                f"{type(index).__name__}."
            )
            console.error(message=message, error=TypeError)
        if self.device_count == 0:
            message = (
                f"No ZaberDevice objects are available for retrieval from ZaberConnection class for {self.port} port. "
                f"This indicates that no valid zaber devices are currently connected to the port managed by the "
                f"connection class or that the connect() class method was not called or otherwise failed."
            )
            console.error(message=message, error=ValueError)
        if index < 0 or index >= self.device_count:
            message = (
                f"Invalid 'index' argument value encountered when retrieving ZaberDevice object from ZaberConnection "
                f"class for {self.port} port. The range of valid index inputs is from 0 to {self.device_count - 1}, "
                f"but encountered index {index}."
            )
            console.error(message=message, error=ValueError)

        return self._devices[index]
