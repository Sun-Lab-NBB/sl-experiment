from typing import Any
from dataclasses import field, dataclass

from _typeshed import Incomplete
from zaber_motion import Units
from zaber_motion.ascii import Axis, Device, Connection

def _attempt_connection(port: str) -> dict[int, Any] | str:
    """Checks the input USB port for Zaber devices (controllers) and parses ID information for any discovered device.

    Args:
        port: The name of the USB port to scan for Zaber devices (eg: COM1, USB0, etc.).

    Returns:
        The dictionary with the ID information of the discovered device(s), if zaber devices were discovered. If zaber
        devices were not found, returns the error message
    """

def _scan_active_ports() -> tuple[dict[str, Any], tuple[str, ...]]:
    """Scans all available Serial (USB) ports and, for each port, returns the ID data for each connected Zaber device.

    This method is intended to be used during the initial device configuration and testing to quickly discover what
    Zaber devices are available on the host-system. Additionally, it returns device configuration information, which is
    helpful during debugging and calibration.

    Returns:
        A tuple with two elements. The first element contains the dictionary that uses port names as keys and either
        lists all discovered zaber devices alongside their ID information or 'None' if any given port does not have
        discoverable Zaber devices. The second element is a tuple of error messages encountered during the scan.
    """

def _format_device_info(device_info: dict[str, Any]) -> str:
    """Formats the device and axis ID information discovered during port scanning as a table before displaying it to
     the user.

    Args:
        device_info: The dictionary containing the device and axis ID information for each scanned port.

    Returns:
        A string containing the formatted device and axis ID information as a table.
    """

def discover_zaber_devices(silence_errors: bool = True) -> None:
    """Scans all available serial ports and displays information about connected Zaber devices.

    Args:
        silence_errors: Determines whether to display encountered errors. By default, when the discovery process runs
            into an error, it labels the error port as having no devices and suppresses the error. Enabling this flag
            will also print encountered error messages, which may be desirable for debugging purposes.
    """

class CRCCalculator:
    """A CRC32-XFER checksum calculator that works with raw bytes or pythonic strings.

    This utility class exposes methods that generate CRC checksum labels and bytes objects, which are primarily used by
    Zaber binding classes to verify that Zaber devices have been configured to work with the binding interface exposed
    by this library.

    Attributes:
        _calculator: Stores the configured Calculator class object used to calculate the checksums.
    """

    _calculator: Incomplete
    def __init__(self) -> None: ...
    def string_checksum(self, string: str) -> int:
        """Calculates the CRC32-XFER checksum for the input string.

        The input strings are first converted to bytes using ASCII protocol. The checksum is then calculated on the
        resultant bytes-object.

        Args:
            string: The string for which to calculate the CRC checksum.

        Returns:
            The integer CRC32-XFER checksum.
        """
    def bytes_checksum(self, data: bytes) -> int:
        """Calculates the CRC32-XFER checksum for the input bytes.

        While the class is primarily designed for generating CRC-checksums for strings, this method can be used to
        checksum any bytes-converted object.

        Args:
            data: The bytes-converted data to calculate the CRC checksum for.

        Returns:
            The integer CRC32-XFER checksum.
        """

@dataclass(frozen=True)
class _ZaberSettings:
    """Maps Zaber setting codes to descriptive names.

    This class functions as an additional abstraction layer that simplifies working with Zaber device and axis setting
    interface.

    Notes:
        This class only lists the settings used by the classes of this module and does not cover all available Zaber
        settings.
    """

    device_temperature: str = ...
    axis_maximum_speed: str = ...
    axis_acceleration: str = ...
    axis_maximum_limit: str = ...
    axis_minimum_limit: str = ...
    axis_temperature: str = ...
    axis_inversion: str = ...
    axis_position: str = ...
    device_code: str = ...
    device_shutdown_flag: str = ...
    axis_linear_flag: str = ...
    axis_park_position: str = ...
    axis_calibration_position: str = ...
    axis_mount_position: str = ...

@dataclass(frozen=True)
class _ZaberUnits:
    """Exposes methods for selecting appropriate Zaber units used when communicating with the motor, based on the
    selected motor type and colloquial unit family.

    This class is primarily designed to de-couple colloquial unit names used by our API from the Zaber-defined unit
    names, which is critical for reading and writing hardware settings and when issuing certain commands. To do so,
    after the initial configuration, use class properties to retrieve the necessary units (e.g: for displacement,
    velocity, or acceleration).
    """

    zaber_units_conversion: dict[str, Any] = field(default_factory=Incomplete)
    unit_type: str = ...
    @property
    def displacement_units(self) -> Units:
        """Returns the Units class instance used to work with displacement (length) data."""
    @property
    def acceleration_units(self) -> Units:
        """Returns the Units class instance used to work with acceleration data.

        Note, all acceleration units are given in units / seconds^2.
        """
    @property
    def velocity_units(self) -> Units:
        """Returns the Units class instance used to work with velocity (speed) data.

        Note, all velocity units are given in units / seconds.
        """

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

    _motor: Axis
    _name: str
    _linear: bool
    _park_position: int
    _valve_position: int
    _mount_position: int
    _max_limit: float
    _min_limit: float
    _units: _ZaberUnits
    _timer: Incomplete
    _shutdown_flag: bool
    def __init__(self, motor: Axis) -> None: ...
    def __repr__(self) -> str:
        """Constructs and returns a string that represents the class instance."""
    def _ensure_call_padding(self) -> None:
        """This method should be used before each call to motor hardware to ensure it is sufficiently separated
        from other calls to prevent overwhelming the serial connection.

        This method is statically configured to prevent further commands from being issued for the following 10
        milliseconds, which is appropriate for the default Zaber communication baudrate of 115,200.
        """
    def _reset_pad_timer(self) -> None:
        """Resets the PrecisionTimer instance used to enforce a static delay between motor hardware calls.

        This method should be used after each motor hardware call command to reset the timer in preparation for the
        next call (to exclude the time spent on the request-response sequence of the call from the padding
        calculation). It is designed to work together with the _ensure_call_padding method.
        """
    def get_position(self, native: bool = False) -> float:
        """Returns the current absolute position of the motor relative to the home position.

        Args:
            native: Determines if the returned value should use native motor units (true) or metric units (false). For
            linear axes, the metric units are millimeters. For rotary axes, the metric units are degrees.
        """
    @property
    def is_homed(self) -> bool:
        """Returns True if the motor has a motion reference point (has been homed)."""
    @property
    def is_parked(self) -> bool:
        """Returns True if the motor is parked."""
    @property
    def is_busy(self) -> bool:
        """Returns True if the motor is currently executing a motor command (is moving)."""
    @property
    def name(self) -> str:
        """Returns the user-defined string-name of the motor axis, e.g.: 'Pitch_Axis'."""
    @property
    def inversion(self) -> bool:
        """Returns the current value of the motor hardware inversion flag.

        Generally, this determines which direction of movement brings the motor towards its home sensor position.
        """
    @property
    def maximum_limit(self) -> float:
        """Returns the maximum absolute position, relative to the home sensor position, the motor can be moved to.

        It is assumed that the home sensor position is always defined as 0. The returned position is in
        millimeters for linear axes and degrees for rotary axes.
        """
    @property
    def minimum_limit(self) -> float:
        """Returns the minimum absolute position relative to the home sensor position the motor can be moved to.

        It is assumed that the home sensor position is always defined as 0. The returned position is in
        millimeters for linear axes and degrees for rotary axes.
        """
    @property
    def park_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved before it is parked.

        This position is applied to the motor before parking to promote a safe homing procedure once the motor is
        unparked. Parking the motor in a predetermined position avoids colliding with other objects in the environment
        during homing and provides a starting point for calibrating the motor's position for new animals.
        """
    @property
    def valve_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved before calibrating
        the water reward valve of the Mesoscope-VR system.

        Applying this position to the motor orients the headbar and lickport system in a way that provides easy access
        to the components of the water delivery system. In turn, this simplifies calibrating, flushing, and filling the
        system with water.
        """
    @property
    def mount_position(self) -> int:
        """Returns the absolute position, in native motor units, where the motor needs to be moved before mounting
        the animal onto the VR rig.

        Applying this position to the motor orients the headbar and lickport system in a way that makes it easier to
        mount the animal, while also providing the animal with a comfortable position inside the VR rig.
        """
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
    def park(self) -> None:
        """Parks the motor, which makes it unresponsive to motor commands and stores current absolute motor position in
        non-volatile memory.

        This method is mostly used to avoid re-homing the device after power cycling, as parking ensures the reference
        point for the motor is maintained in non-volatile memory. Additionally, parking is used to lock the motor
        in place as an additional safety measure.
        """
    def unpark(self) -> None:
        """Unparks a parked motor, which allows the motor to accept and execute motion commands."""
    def shutdown(self) -> None:
        """Prepares the motor for shutting down by moving the motor to a hardware-defined shutdown parking position.

        This method has to be called at the end of each class runtime to ensure the class can be reused without manual
        intervention later.

        Notes:
            This method contains the guards that prevent it from being executed if the motor has already been shut down.
        """
    def emergency_shutdown(self) -> None:
        """Stops and parks the motor.

        This method purposefully avoids moving the motor to the park position before shutdown. It is designed to be
        called in the case of emergency, when the managing runtime crashes. Users should use the default 'shutdown'
        method.
        """

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

    _device: Device
    _id: int
    _name: str
    _label: str
    _axis: ZaberAxis
    _crc_calculator: CRCCalculator
    _shutdown_flag: bool
    def __init__(self, device: Device) -> None: ...
    def __repr__(self) -> str:
        """Constructs and returns a string that represents the class."""
    def shutdown(self) -> None:
        """Shuts down the axis (motor) managed by the device and changes the shutdown tracker non-volatile variable of
        the device to 1.

        Notes:
            This method is intended to be called by the parent ZaberConnection class as part of the disconnect()
            method runtime.
        """
    def emergency_shutdown(self) -> None:
        """Stops and parks the managed motor axes, but does not reset the shutdown flag.

        This method is designed to be used exclusively by the __del__ method of the managing ZaberConnection class to
        end the runtime.
        """
    @property
    def label(self) -> str:
        """Returns the label (user-assigned descriptive name) of the device."""
    @property
    def name(self) -> str:
        """Returns the name (manufacturer-assigned hardware name) of the device."""
    @property
    def id(self) -> int:
        """Returns the unique numeric ID of the device."""
    @property
    def axis_information(self) -> dict[str, str]:
        """Returns a dictionary that provides the basic ID information about the axis controlled by this device."""
    @property
    def axis(self) -> ZaberAxis:
        """Returns the ZaberAxis class reference for the axis (motor) managed by the ZaberDevice instance."""

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

    _port: str
    _connection: Connection | None
    _devices: tuple[ZaberDevice, ...]
    _is_connected: bool
    def __init__(self, port: str) -> None: ...
    def __repr__(self) -> str:
        """Constructs and returns a string that represents the class."""
    def __del__(self) -> None:
        """Ensures that the connection is shut down gracefully whenever the class instance is deleted."""
    def connect(self) -> None:
        """Opens the serial port and automatically detects and connects to any available Zaber devices (controllers).

        Depending on the input arguments, the method may also raise or print exception messages to inform the user of
        the cause of the runtime failure.

        Raises:
            NoDeviceFoundException: If no compatible Zaber devices are discovered using the target serial port.
        """
    def disconnect(self) -> None:
        """Shuts down all controlled Zaber devices and closes the connection.

        Notes:
            Make sure it is safe to park the motor before this method is called. Calling it will move the motor which
            may damage the environment or motors.

        Specifically, loops over each connected device and triggers its shutdown() method to execute the necessary
        pre-disconnection procedures. Then, disconnects from the serial port and clears the device list.
        """
    @property
    def is_connected(self) -> bool:
        """Returns True if the class has established connection with the managed serial port."""
    @property
    def port(self) -> str:
        """Returns the name of the serial port used by the connection."""
    @property
    def device_information(self) -> dict[int, Any]:
        """Returns a dictionary that provides the basic ID information about all Zaber devices using this connection."""
    @property
    def device_count(self) -> int:
        """Returns the number of Zaber devices using this connection."""
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
