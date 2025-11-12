"""This module provides the interfaces for Zaber devices used in the Mesoscope-VR data acquisition system."""

from typing import Any
from dataclasses import field, dataclass
from collections.abc import Callable

from crc import Calculator, Configuration
from tabulate import tabulate
from zaber_motion import Tools
from ataraxis_time import PrecisionTimer, TimerPrecisions
from zaber_motion.ascii import Axis, Device, Connection, SettingConstants
from ataraxis_base_utilities import LogLevel, console


@dataclass
class _ZaberAxisData:
    """Stores the identification data for an axis of a Zaber device."""

    axis_id: int
    """The unique motor type code of the axis."""
    axis_label: str
    """THe user-assigned name of the axis."""


@dataclass
class _ZaberDeviceData:
    """Stores the identification data about a Zaber device."""

    device_number: int
    """The positional index of the device in the daisy-chain of devices connected to the same serial port."""
    device_id: int
    """The unique identifier code of the device."""
    label: str
    """The user-assigned name of the device."""
    name: str
    """The manufacturer-assigned name of the device."""
    axes: list[_ZaberAxisData] = field(default_factory=list)
    """Stores _ZaberAxisData instances for each axis managed by this device."""


@dataclass
class _ZaberPortData:
    """Stores the identification data for all Zaber devices connected to a serial port."""

    port_name: str
    """The name of the USB port."""
    devices: list[_ZaberDeviceData] = field(default_factory=list)
    """Stores _ZaberDeviceData instances for each device connected to this port."""

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
                _ZaberAxisData(axis_id=axis_num, axis_label=device.get_axis(axis_number=axis_num).label or "Not Used")
                for axis_num in range(1, device.axis_count + 1)
            ]

            device_info = _ZaberDeviceData(
                device_number=num + 1, device_id=device.device_id, label=device.label, name=device.name, axes=axes
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
                    device.name,
                ]
                for axis in device.axes:
                    axis_row = [*device_row, str(axis.axis_id), axis.axis_label]
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
    """Exposes methods for calculating CRC32-XFER checksums for ASCII strings.

    Attributes:
        _calculator: The configured Calculator instance used to calculate the checksums.
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

        Args:
            string: The string for which to calculate the CRC checksum.

        Returns:
            The integer CRC32-XFER checksum.
        """
        return self._calculator.checksum(data=bytes(string, "ASCII"))


# Initializes a shared CRCCalculator instance used by the ZaberDevice class instances to verify the interfaced device's
# configuration.
_crc_calculator = CRCCalculator()


@dataclass(frozen=True)
class _ZaberSettings:
    """Defines the set of codes used to access Zaber settings stored in each interfaced device's non-volatile memory."""

    maximum_limit: str = SettingConstants.LIMIT_MAX
    """The maximum absolute position, in native motor units, the motor is allowed to reach during runtime, relative to 
    the motor's home position."""
    minimum_limit: str = SettingConstants.LIMIT_MIN
    """The minimum absolute position, in native motor units, the motor is allowed to reach during runtime, relative to 
    the motor's home position."""
    position: str = SettingConstants.POS
    """The current absolute position of the motor, in native motor units, relative to its home position."""
    checksum: str = SettingConstants.USER_DATA_0
    """The CRC32 checksum that should match the checksum of the device's label, which is used to confirm that the 
    device has been configured to work with the bindings exposed by this library. Uses USER_DATA 0 variable."""
    shutdown_flag: str = SettingConstants.USER_DATA_1
    """Tracks whether the device has been properly shut down during the previous runtime. Uses USER_DATA 1 variable."""
    unsafe_flag: str = SettingConstants.USER_DATA_10
    """Tracks whether the device can be positioned in a way that is not safe to home after power cycling. 
    Uses USER_DATA 10 variable."""
    axis_park_position: str = SettingConstants.USER_DATA_11
    """The absolute position, in native motor units, where the motor should be moved to before parking and shutting 
    down. Uses USER_DATA 11 variable."""
    axis_maintenance_position: str = SettingConstants.USER_DATA_12
    """The absolute position, in native motor units, where the motor should be moved as part of the preparation for the
    system's maintenance. Uses USER_DATA 12 variable.
    """
    axis_mount_position: str = SettingConstants.USER_DATA_13
    """The absolute position, in native motor units, where the motor should be moved before mounting the animal into the
    system's enclosure. Uses USER_DATA 13 variable.
    """


class ZaberAxis:
    """Interfaces with a Zaber motor (axis).

    Notes:
        This class represents the lowest level of the tri-class hierarchy used to control Zaber motors during runtime.

    Args:
        motor: The Axis class instance that interfaces with the motor's hardware.

    Attributes:
        _motor: The Axis class instance that physically controls the motor's hardware through Zaber ASCII protocol.
        _park_position: The absolute position, in native motor units, where the motor should be moved to before parking
            and shutting down.
        _maintenance_position: The absolute position, in native motor units, where the motor should be moved as part of
            the preparation for the system's maintenance.
        _mount_position: The absolute position, in native motor units, where the motor should be moved before mounting
            the animal into the system's enclosure.
        _maximum_limit: The maximum absolute position relative to the home sensor position, in native motor units,
            the motor hardware can reach.
        _minimum_limit: The minimum absolute position relative to the home sensor position, in native motor units,
            the motor hardware can reach.
        _shutdown_flag: Tracks whether the motor has been shut down.
        _timer: A PrecisionTimer class instance that is used to ensure that communication with the motor is carried out
            at a pace that does not overwhelm the connection interface with too many successive calls.

    Raises:
        ValueError: If any parameter is read from the motor's non-volatile memory is outside the expected range of
            values.
    """

    _COMMUNICATION_DELAY_MS: int = 5
    """The minimum delay, in milliseconds, that must separate all consecutive interactions with the motor's 
    hardware."""

    def __init__(self, motor: Axis) -> None:
        # Pre-initializes the shutdown tracker early
        self._shutdown_flag: bool = False

        # Parses hardcoded information stored in non-volatile hardware memory:
        self._motor: Axis = motor
        self._park_position: int = int(self._motor.device.settings.get(setting=_ZaberSettings.axis_park_position))
        self._maintenance_position: int = int(
            self._motor.device.settings.get(setting=_ZaberSettings.axis_maintenance_position)
        )
        self._mount_position: int = int(self._motor.device.settings.get(setting=_ZaberSettings.axis_mount_position))
        self._maximum_limit: float = self._motor.settings.get(setting=_ZaberSettings.maximum_limit)
        self._minimum_limit: float = self._motor.settings.get(setting=_ZaberSettings.minimum_limit)

        # Verifies that all predefined axis positions fall within the axis motion limits.
        if self._park_position < self._minimum_limit or self._park_position > self._maximum_limit:
            message = (
                f"Invalid parking position hardware parameter value encountered when initializing ZaberAxis class for "
                f"{self._motor.label} axis of the Device {self._motor.device.label}. Expected a value between "
                f"{self._minimum_limit} and {self._maximum_limit}, but read {self._park_position}."
            )
            console.error(message=message, error=ValueError)
        if self._maintenance_position < self._minimum_limit or self._maintenance_position > self._maximum_limit:
            message = (
                f"Invalid system maintenance position hardware parameter value encountered when initializing ZaberAxis "
                f"class for {self._motor.label} axis of the Device {self._motor.device.label}. Expected a value "
                f"between {self._minimum_limit} and {self._maximum_limit}, but read {self._maintenance_position}."
            )
            console.error(message=message, error=ValueError)
        if self._mount_position < self._minimum_limit or self._mount_position > self._maximum_limit:
            message = (
                f"Invalid animal mounting position hardware parameter value encountered when initializing ZaberAxis "
                f"class for {self._motor.label} axis of the Device {self._motor.device.label}. Expected a value"
                f" between {self._minimum_limit} and {self._maximum_limit}, but read {self._mount_position}."
            )
            console.error(message=message, error=ValueError)

        # Initializes a timer to ensure the class cannot issue commands fast enough to overwhelm the motor communication
        # interface.
        self._timer: PrecisionTimer = PrecisionTimer(precision=TimerPrecisions.MILLISECOND)

    def __repr__(self) -> str:
        """Returns the instance's string representation."""
        return (
            f"ZaberAxis(name={self._motor.label}, homed={self.is_homed}, parked={self.is_parked}, busy={self.is_busy}, "
            f"position={self.get_position()})."
        )

    def _padded_method_call(self, method: Callable, *args: Any, **kwargs: Any) -> Any:
        """Interacts with the motor hardware by executing the requested method with the appropriate time padding to
        prevent overwhelming the communication interface.

        Args:
            method: The method to call with timing guards.
            *args: Positional arguments to pass to the method.
            **kwargs: Keyword arguments to pass to the method.

        Returns:
            The value returned by the specified method's call.
        """
        # Ensures that at least 5 milliseconds have elapsed since the previous interaction with the motor's hardware.
        # This design is chosen over delay() to allow instantaneous escapes if this method is called when the delay
        # has already expired
        while self._timer.elapsed < self._COMMUNICATION_DELAY_MS:
            pass

        # Executes the requested method
        result = method(*args, **kwargs)

        # Resets the padding timer and returns the call result
        self._timer.reset()
        return result

    def get_position(self) -> float:
        """Returns the current absolute position of the motor, in native motor units, relative to its home position."""
        return self._padded_method_call(method=self._motor.get_position)

    @property
    def is_homed(self) -> bool:
        """Returns True if the motor has been homed (has a motion reference point)."""
        return self._padded_method_call(method=self._motor.is_homed)

    @property
    def is_parked(self) -> bool:
        """Returns True if the motor is parked."""
        return self._padded_method_call(method=self._motor.is_parked)

    @property
    def is_busy(self) -> bool:
        """Returns True if the motor is currently executing a command (is moving)."""
        return self._padded_method_call(method=self._motor.is_busy)

    @property
    def park_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved as part of the
        system's shutdown procedure.
        """
        return self._park_position

    @property
    def maintenance_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved as part of preparing
        the system for maintenance.
        """
        return self._maintenance_position

    @property
    def mount_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved before mounting
        the animal into the system's enclosure.
        """
        return self._mount_position

    def home(self) -> None:
        """Homes the motor by moving it towards the home sensor position until it triggers the sensor.

        Notes:
            This method establishes a stable reference point used to execute all other motion commands.

            The method initializes the homing procedure but does not block until it is over. This feature is designed
            to support homing multiple motors in parallel.
        """
        # A parked motor cannot be homed until it is unparked. As a safety measure, this command does NOT automatically
        # override the parking state. Additionally, the motor is not allowed to execute a home command unless it is
        # idle.
        if self.is_parked or self.is_busy:
            return

        # If the motor has already been homed, first moves it to the parking position. The reason behind this
        # implementation instead of the default 'home' command is to handle a case unique to rotary axis that has been
        # artificially limited to a certain motion range. For the Mesoscope-VR system, it is the headbar yaw axis,
        # which can collide with a physical limiter if it is homed when it is 'below' home sensor.
        if self.is_homed:
            self._padded_method_call(self._motor.move_absolute, position=self._park_position, wait_until_idle=False)

        # Moves the motor towards the home sensor until it triggers the limit switch. This is the default 'home' action
        # intended to only be triggered from the default parking position.
        self._padded_method_call(self._motor.home, wait_until_idle=False)

    def move(self, position: int) -> None:
        """Moves the motor to the requested absolute position.

        Notes:
            This method initiates the movement, but does not wait until it is completed. This behavior is designed to
            enable parallel operation of multiple motors.

        Args:
            position: The exact position, in native motor units, to move the motor to.
        """
        # If the motor is already executing a different command, it has to be stopped or allowed to finish the command
        # before executing a new command. Also, movement is only allowed if the motor is not parked and has been homed.
        if self.is_busy or not self.is_homed or self.is_parked:
            return

        # Ensures that the position to move the motor to is within the motor's software limits.
        if position < self._minimum_limit or position > self._maximum_limit:
            return

        # Initiates the movement of the motor
        self._padded_method_call(self._motor.move_absolute, position=position, wait_until_idle=False)

    def stop(self) -> None:
        """Decelerates and stops the motor.

        Notes:
            This method can be called to interrupt other currently running methods, which is primarily used in the case
            of an emergency.

            Calling this method once instructs the motor to decelerate and stop. Calling this method twice in a row
            instructs the motor to stop immediately (without deceleration).

            This command does not block until the motor stops to allow stopping multiple motors (axes) in rapid
            succession.
        """
        # This is the only command that does not have a padding timer check. This design pattern is to allow calling
        # this method in the case of an emergency to shut down the managed motor.
        self._motor.stop(wait_until_idle=False)
        self._timer.reset()  # Manually resets the timer, since stop commands are not routed through the padding method.

    def park(self) -> None:
        """Parks the motor, making it unresponsive to motor commands, and stores the current absolute position of the
        motor in its non-volatile memory.
        """
        # The motor has to be idle to be parked.
        if self.is_busy:
            return

        self._padded_method_call(self._motor.park)

    def unpark(self) -> None:
        """Unparks a parked motor, which allows the motor to accept and execute motion commands."""
        if self._motor.is_parked():
            self._padded_method_call(self._motor.unpark)

    def shutdown(self) -> None:
        """Prepares the motor for shutting down by seizing any ongoing movement and parking it to cache its current
        position to the non-volatile memory.
        """
        # If the shutdown flag indicates that the motor has already been shut, abort early. Also returns early if the
        # motor is already parked.
        if self._shutdown_flag or self.is_parked:
            self._shutdown_flag = True  # Ensures that the shutdown flag is set
            return

        # If the motor is moving, stops it
        if self.is_busy:
            self._motor.stop(wait_until_idle=True)

        # Parks the motor and sets the shutdown flag.
        self.park()
        self._shutdown_flag = True


class ZaberDevice:
    """Manages a Zaber controller (device) that manages one or more motors (axes).

    Notes:
        This class represents the intermediate level of the tri-class hierarchy used to control Zaber motors during
        runtime.

        This class is explicitly designed to work with devices that manage a single axis (motor) and raises errors
        if it is initialized for a controller with more than a single axis.

    Args:
        device: The Device class instance that interfaces with the controller's hardware.

    Attributes:
        _controller: The Device class instance that interfaces with the Zaber controller's hardware.
        _axis: Stores the ZaberAxis class instance that interfaces with the motor managed by this instance.
        _shutdown_flag: Tracks whether the device has been shut down.

    Raises:
        ValueError: If the device checksum stored in the device's non-volatile memory does not match the CRC32-XFER
            checksum of the device's label. If the device is unsafe and has not been properly shut down during the
            previous runtime as indicated by its non-volatile trackers. If the device manages more than a single axis
            (motor).
    """

    def __init__(self, device: Device) -> None:
        # Extracts and records the necessary ID information about the device
        self._controller: Device = device

        # Ensures that the device is managing a single axis.
        if device.axis_count != 1:
            message = (
                f"Unexpected value encountered when checking the number of axes (motors) managed by the device "
                f"{self._controller.label}. Currently, ZaberDevice instances only work with devices (controllers) that "
                f"manage a single Axis (motor). Instead, the device has {device.axis_count} axes, which indicates that "
                f"it manages multiple motors."
            )
            console.error(message=message, error=ValueError)

        # Initializes the ZaberAxis class to interface with the motor managed by the Device.
        self._axis: ZaberAxis = ZaberAxis(motor=self._controller.get_axis(axis_number=1))

        # Uses the CRC calculator to generate the checksum for the device's label. It is expected that the
        # device_code (USER_DATA_0) non-volatile variable of the device is set to this checksum for any
        # correctly configured device.
        device_check: int = _crc_calculator.string_checksum(self._controller.label)
        device_code: int = int(device.settings.get(setting=_ZaberSettings.checksum))
        if device_code != device_check:
            message = (
                f"Unable to verify that the ZaberDevice instance for the {self._controller.label} "
                f"({self._controller.name}) device is configured to work with ZaberDevice instances. Based on the "
                f"device's label '{self._controller.label}', expected the validation checksum of {device_check}, but "
                f"read {device_code}. The non-volatile memory variable used to store this data is USER_DATA_0."
            )
            console.error(message=message, error=ValueError)

        # Verifies that the device has been properly shut down during the previous runtime. While this is not an issue
        # for most motors, certain motors require to be positioned in a specific way to ensure they can be homed. These
        # motors use the 'unsafe_flag' non-volatile tracker to indicate that they require proper shutdown.
        shutdown_flag: bool = bool(self._controller.settings.get(setting=_ZaberSettings.shutdown_flag))
        unsafe_flag: bool = bool(self._controller.settings.get(setting=_ZaberSettings.unsafe_flag))
        if not shutdown_flag and unsafe_flag:
            message = (
                f"Unable to initialize ZaberDevice class instance for the {self._controller.label} "
                f"({self._controller.name}) device, as it was not properly shutdown during the previous runtime. Since "
                f"the device is marked as 'unsafe,' it is not possible to reset the device automatically. Ensure that "
                f"the device is positioned correctly for homing procedure and manually set the value of the shutdown "
                f"tracker to 1. The non-volatile memory variable used to store this data is USER_DATA_1."
            )
            console.error(message=message, error=ValueError)

        # Sets the device's shutdown tracker to 0. This tracker is used to detect when a device is not properly shut
        # down, which may have implications for the use of the device, such as the ability to home the device.
        # During the proper shutdown procedure, the tracker is always set to 1, so setting it to 0 now allows
        # detecting cases where the shutdown is not carried out.
        self._controller.settings.set(setting=_ZaberSettings.shutdown_flag, value=0)
        self._shutdown_flag = False  # Also sets the local shutdown flag

    def __repr__(self) -> str:
        """Returns the string representation of the instance."""
        return (
            f"ZaberDevice(name='{self._controller.name}', label={self._controller.label}, "
            f"id={self._controller.device_id})"
        )

    def shutdown(self) -> None:
        """Gracefully shuts down the motor (axis) managed by this controller."""
        # Shuts down the managed axis (motor).
        self._axis.shutdown()

        # Sets the shutdown flag to 1 to indicate that the shutdown procedure has been performed.
        self._controller.settings.set(setting=_ZaberSettings.shutdown_flag, value=1)
        self._shutdown_flag = True  # Also sets the local shutdown flag

    @property
    def axis(self) -> ZaberAxis:
        """Returns the ZaberAxis instance that allows interfacing with the motor (axis) managed by this Zaber
        controller.
        """
        return self._axis


class ZaberConnection:
    """Interfaces with a serial USB port and all Zaber devices (controllers) and axes (motors) available through that
    port.

    Notes:
        This class represents the highest level of the tri-class Zaber binding hierarchy.

        This class does not automatically initialize the connection with the port. Call the connect() method to
        establish connection before calling other class methods.

    Args:
        port: The name of the USB port to connect to.

    Attributes:
        _port: Stores the name of the serial port to connect to.
        _connection: The Connection class instance that manages the specified serial port and all Zaber devices using
            the port.
        _devices: The tuple of ZaberDevice instances used to interface with Zaber devices available through the
            connected port.
        _is_connected: Tracks whether the instance is currently connected to the managed serial port.

    Raises:
        TypeError: If the provided 'port' argument value is not a string.
    """

    def __init__(self, port: str) -> None:
        if not isinstance(port, str):
            message = (
                f"Invalid 'port' argument type encountered when initializing a ZaberConnection class instance. "
                f"Expected a {type(str).__name__}, but encountered {port} of type {type(port).__name__}."
            )
            console.error(message=message, error=TypeError)

        self._port: str = port
        self._connection: Connection | None = None
        self._devices: tuple[ZaberDevice, ...] = ()
        self._is_connected: bool = False

    def __repr__(self) -> str:
        """Returns the string representation of the instance."""
        return f"ZaberConnection(port='{self._port}', connected={self.is_connected})"

    def __del__(self) -> None:
        """Ensures that the instance shuts down all managed devices and disconnects from the managed port before it is
        garbage-collected.
        """
        if self._connection is not None and self.is_connected:
            # If the connection is still active ensures all managed devices are properly shut down.
            for device in self._devices:
                device.shutdown()

            # Closes the connection
            self._connection.close()

    def connect(self) -> None:
        """Opens the serial port and detects and connects to any available Zaber devices (controllers).

        Raises:
            NoDeviceFoundException: If no compatible Zaber devices are discovered using the target serial port.
        """
        # If the connection is already established, prevents from attempting to re-establish the connection again.
        if self.is_connected:
            return

        # Establishes connection
        self._connection = Connection.open_serial_port(port_name=self._port, direct=False)
        self._is_connected = True

        # Gets the list of all connected Zaber devices.
        devices: list[Device] = self._connection.detect_devices()

        # Packages each discovered Device into a ZaberDevice class instance and builds the internal device interface
        # tuple.
        self._devices = tuple([ZaberDevice(device=device) for device in devices])

    def disconnect(self) -> None:
        """Shuts down all managed Zaber devices and closes the connection."""
        # Prevents the method from running if the connection is not established.
        if not self.is_connected:
            return

        # Loops over each connected device and triggers its shutdown procedure
        for device in self._devices:
            device.shutdown()

        # Releases all runtime assets
        self._devices = ()
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
            except Exception:
                # Otherwise, the connection is broken
                self._is_connected = False
            else:
                self._is_connected = True  # If device check succeeded the connection is active
                return True
        return self._is_connected

    def get_device(self, index: int) -> ZaberDevice:
        """Returns the ZaberDevice instance for the requested Zaber controller (device).

        Args:
            index: The index of the controller for which to retrieve the interface. The controllers are indexed based
                on their position in the daisy-chain of Zaber devices relative to the USB port, with the device
                directly connected to the port having an index of 0.

        Returns:
            A ZaberDevice instance that interfaces with the specified controller.

        Raises:
            ConnectionError : If the instance is not connected to the managed serial port.
        """
        # Prevents retrieving the device data if the connection has not been established.
        if not self.is_connected:
            message = (
                f"Unable to retrieve the Zaber device at index {index} as the ZaberConnection instance has not "
                f"established the connection with the managed port ({self._port})."
            )
            console.error(message=message, error=ConnectionError)

        return self._devices[index]
