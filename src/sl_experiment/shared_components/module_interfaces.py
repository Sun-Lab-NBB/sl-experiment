"""This module provides the interfaces (ModuleInterface class implementations) for the hardware designed in the Sun lab.
These interfaces are designed to work with the hardware modules assembled and configured according to the instructions
from our microcontrollers' library: https://github.com/Sun-Lab-NBB/sl-micro-controllers."""

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray
from ataraxis_time import PrecisionTimer
from scipy.optimize import curve_fit
from ataraxis_base_utilities import console
from ataraxis_data_structures import SharedMemoryArray
from ataraxis_communication_interface import (
    ModuleData,
    ModuleState,
    ModuleInterface,
)

# Pre-creates NumPy constants used when resetting SharedMemoryArray instances to optimize runtime performance.
_zero_uint = np.uint64(0)
_zero_float = np.float64(0.0)


class EncoderInterface(ModuleInterface):
    """Interfaces with EncoderModule instances running on Ataraxis MicroControllers.

    EncoderModule allows interfacing with quadrature encoders used to monitor the direction and magnitude of a connected
    object's rotation. To achieve the highest resolution, the module relies on hardware interrupt pins to detect and
    handle the pulses sent by the two encoder channels.

    Notes:
        This interface sends CW and CCW motion data to Unity via the 'LinearTreadmill/Data' MQTT topic.

        The default initial encoder readout is zero (no CW or CCW motion). The class instance is zeroed at communication
        initialization.

    Args:
        encoder_ppr: The resolution of the managed quadrature encoder, in Pulses Per Revolution (PPR). This is the
            number of quadrature pulses the encoder emits per full 360-degree rotation. If this number is not known,
            provide a placeholder value and use the get_ppr () command to estimate the PPR using the index channel of
            the encoder.
        object_diameter: The diameter of the rotating object connected to the encoder, in centimeters. This is used to
            convert encoder pulses into rotated distance in cm.
        cm_per_unity_unit: The length of each Unity 'unit' in centimeters. This is used to translate raw encoder pulses
            into Unity 'units' before sending the data to Unity.
        debug: A boolean flag that configures the interface to dump certain data received from the microcontroller into
            the terminal. This is used during debugging and system calibration and should be disabled for most runtimes.

    Attributes:
        _motion_topic: Stores the MQTT motion topic.
        _ppr: Stores the resolution of the managed quadrature encoder.
        _object_diameter: Stores the diameter of the object connected to the encoder.
        _cm_per_pulse: Stores the conversion factor that translates encoder pulses into centimeters.
        _unity_unit_per_pulse: Stores the conversion factor to translate encoder pulses into Unity units.
        _debug: Stores the debug flag.
        _distance_tracker: Stores the SharedMemoryArray that stores the absolute distance traveled by the animal since
            class initialization, in centimeters. Note, the distance does NOT account for the direction of travel. It is
            a monotonically incrementing count of traversed centimeters.
    """

    def __init__(
        self,
        encoder_ppr: int = 8192,
        object_diameter: float = 15.0333,  # 0333 is to account for the wheel wrap
        cm_per_unity_unit: float = 10.0,
        debug: bool = False,
    ) -> None:
        data_codes: set[np.uint8] = {np.uint8(51), np.uint8(52), np.uint8(53)}  # kRotatedCCW, kRotatedCW, kPPR

        super().__init__(
            module_type=np.uint8(2),
            module_id=np.uint8(1),
            data_codes=data_codes,
            error_codes=None,
        )

        # Saves additional data to class attributes.
        self._motion_topic: str = "LinearTreadmill/Data"  # Hardcoded output topic
        self._ppr: int = encoder_ppr
        self._object_diameter: float = object_diameter
        self._debug: bool = debug

        # Computes the conversion factor to go from pulses to centimeters
        self._cm_per_pulse: np.float64 = np.round(
            a=np.float64((math.pi * self._object_diameter) / self._ppr),
            decimals=8,
        )

        # Computes the conversion factor to translate encoder pulses into unity units. Rounds to 8 decimal places for
        # consistency and to ensure repeatability.
        self._unity_unit_per_pulse: np.float64 = np.round(
            a=np.float64((math.pi * object_diameter) / (encoder_ppr * cm_per_unity_unit)),
            decimals=8,
        )

        # Precreates a shared memory array used to track and share the absolute distance, in centimeters, traveled by
        # the animal since class initialization and the current absolute position of the animal in centimeters relative
        # to onset position.
        self._distance_tracker: SharedMemoryArray = SharedMemoryArray.create_array(
            name=f"{self._module_type}_{self._module_id}_distance_tracker",
            prototype=np.zeros(shape=2, dtype=np.float64),
            exist_ok=True,
        )

    def __del__(self) -> None:
        """Ensures the speed_tracker is properly cleaned up when the class is garbage-collected."""
        self._distance_tracker.disconnect()
        self._distance_tracker.destroy()

    def initialize_remote_assets(self) -> None:
        """Connects to the speed_tracker SharedMemoryArray."""
        self._distance_tracker.connect()

    def terminate_remote_assets(self) -> None:
        """Disconnects from the speed_tracker SharedMemoryArray."""
        self._distance_tracker.disconnect()

    def process_received_data(self, message: ModuleState | ModuleData) -> None:
        """Processes incoming data in real time.

        Motion data (codes 51 and 52) is converted into CW / CCW vectors, translated from pulses to Unity units, and
        is sent to Unity via MQTT. Encoder PPR data (code 53) is printed via the console.

        Also, keeps track of the total distance traveled by the animal since class initialization, relative to the
        initial position at runtime onset and updates the distance_tracker SharedMemoryArray.

        Notes:
            If debug mode is enabled, motion data is also converted to centimeters and printed via the console.
        """
        # Static guard to appease mypy, all processed module messages are ModuleData types at this point.
        if isinstance(message, ModuleState):
            return

        # If the incoming message is the PPR report, prints the data via console.
        if message.event == 53:
            console.echo(f"Encoder ppr: {message.data_object}")

        # Otherwise, the message necessarily has to be reporting rotation into CCW or CW direction
        # (event code 51 or 52).

        # The rotation direction is encoded via the message event code. CW rotation (code 52) is interpreted as negative
        # and CCW (code 51) as positive.
        sign = 1 if message.event == np.uint8(51) else -1

        # Translates the absolute motion into the CW / CCW vector and converts from raw pulse count to Unity units
        # using the precomputed conversion factor. Uses float64 and rounds to 8 decimal places for consistency and
        # precision
        signed_motion = np.round(
            a=np.float64(message.data_object) * self._unity_unit_per_pulse * sign,
            decimals=8,
        )

        # Converts the motion into centimeters. Does NOT include the sign as right now we do not care about the
        # direction of motion with how we use this data.
        cm_motion = np.round(
            a=np.float64(message.data_object) * self._cm_per_pulse,
            decimals=8,
        )

        # Continuously aggregates the distance data into the tracker array.
        distance = self._distance_tracker.read_data(index=0, convert_output=False)
        distance += cm_motion
        self._distance_tracker.write_data(index=0, data=distance)

        # Also updates the current absolute position of the animal (given relative to experiment onset position 0)
        absolute_position = self._distance_tracker.read_data(index=1, convert_output=False)
        absolute_position += signed_motion
        self._distance_tracker.write_data(index=1, data=absolute_position)

        # If the class is in the debug mode, prints the motion data via the console
        if self._debug:
            console.echo(message=f"Encoder moved {cm_motion * sign} cm.")  # Includes the sign here

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(
        self,
        report_ccw: np.bool | bool = np.bool(True),
        report_cw: np.bool | bool = np.bool(True),
        delta_threshold: np.uint32 | int = np.uint32(10),
    ) -> None:
        """Changes the PC-addressable runtime parameters of the EncoderModule instance.

        Use this method to package and apply new PC-addressable parameters to the EncoderModule instance managed by
        this Interface class.

        Args:
            report_ccw: Determines whether to report rotation in the CCW (positive) direction.
            report_cw: Determines whether to report rotation in the CW (negative) direction.
            delta_threshold: The minimum number of pulses required for the motion to be reported. Depending on encoder
                resolution, this allows setting the 'minimum rotation distance' threshold for reporting. Note, if the
                change is 0 (the encoder readout did not change), it will not be reported, regardless of the
                value of this parameter. Sub-threshold motion will be aggregated (summed) across readouts until a
                significant overall change in position is reached to justify reporting it to the PC.
        """
        message = ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            parameter_data=(np.bool(report_ccw), np.bool(report_cw), np.uint32(delta_threshold)),
        )
        self._input_queue.put(message)  # type: ignore

    def check_state(self, repetition_delay: np.uint32 = np.uint32(200)) -> None:
        """Returns the number of pulses accumulated by the EncoderModule since the last check or reset.

        If there has been a significant change in the absolute count of pulses, reports the change and direction to the
        PC. It is highly advised to issue this command to repeat (recur) at a desired interval to continuously monitor
        the encoder state, rather than repeatedly calling it as a one-off command for best runtime efficiency.

        This command allows continuously monitoring the rotation of the object connected to the encoder. It is designed
        to return the absolute raw count of pulses emitted by the encoder in response to the object ration. This allows
        avoiding floating-point arithmetic on the microcontroller and relies on the PC to convert pulses to standard
        units, such as centimeters. The specific conversion algorithm depends on the encoder and motion diameter.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the
                command will only run once.
        """
        command: RepeatedModuleCommand | OneOffModuleCommand
        if repetition_delay == 0:
            command = OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
            )
        else:
            command = RepeatedModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
                cycle_delay=np.uint32(repetition_delay),
            )
        self._input_queue.put(command)  # type: ignore

    def reset_pulse_count(self) -> None:
        """Resets the EncoderModule pulse tracker to 0.

        This command allows resetting the encoder without evaluating its current pulse count. Currently, this command
        is designed to only run once.
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(2),
            noblock=np.bool(False),
        )

        self._input_queue.put(command)  # type: ignore

    def get_ppr(self) -> None:
        """Uses the index channel of the EncoderModule to estimate its Pulse-per-Revolution (PPR).

        The PPR allows converting raw pulse counts the EncoderModule sends to the PC to accurate displacement in
        standard distance units, such as centimeters. This is a service command not intended to be used during most
        runtimes if the PPR is already known. It relies on the object tracked by the encoder completing up to 11 full
        revolutions and uses the index channel of the encoder to measure the number of pulses per each revolution.

        Notes:
            Make sure the evaluated encoder rotates at a slow and stead speed until this command completes. Similar to
            other service commands, it is designed to deadlock the controller until the command completes. Note, the
            EncoderModule does not provide the rotation, this needs to be done manually.

            The direction of the rotation is not relevant for this command, as long as the object makes the full
            360-degree revolution.

            The command is optimized for the object to be rotated with a human hand at a steady rate, so it delays
            further index pin polling for 100 milliseconds each time the index pin is triggered. Therefore, if the
            object is moving too fast (or too slow), the command will not work as intended.
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(3),
            noblock=np.bool(False),
        )
        self._input_queue.put(command)  # type: ignore

    @property
    def mqtt_topic(self) -> str:
        """Returns the MQTT topic used to transfer motion data from the interface to Unity."""
        return self._motion_topic

    @property
    def cm_per_pulse(self) -> np.float64:
        """Returns the conversion factor to translate raw encoder pulse count to distance moved in centimeters."""
        return self._cm_per_pulse

    @property
    def absolute_position(self) -> np.float64:
        """Returns the absolute position of the animal relative to the runtime onset in Unity units.

        The position is given relative to the position at runtime onset ('0').
        """
        return self._distance_tracker.read_data(index=1, convert_output=False)  # type: ignore

    @property
    def traveled_distance(self) -> np.float64:
        """Returns the total distance, in centimeters, traveled by the animal since runtime onset.

        This distance tracker is a monotonically incrementing count of traversed centimeters that does not account for
        the direction of travel.
        """
        return self._distance_tracker.read_data(index=0, convert_output=False)  # type: ignore

    def reset_distance_tracker(self) -> None:
        """Resets the array that tracks the total traveled distance and the absolute position of the animal relative to
        the runtime onset.
        """
        # noinspection PyTypeChecker
        self._distance_tracker.write_data(index=0, data=_zero_float)
        # noinspection PyTypeChecker
        self._distance_tracker.write_data(index=1, data=_zero_float)


class TTLInterface(ModuleInterface):
    """Interfaces with TTLModule instances running on Ataraxis MicroControllers.

    TTLModule facilitates exchanging Transistor-to-Transistor Logic (TTL) signals between various hardware systems, such
    as microcontrollers, cameras, and recording devices. The module contains methods for both sending and receiving TTL
    pulses, but each TTLModule instance can only perform one of these functions at a time.

    Notes:
        When the TTLModule is configured to output a signal, it will notify the PC about the initial signal state
        (HIGH or LOW) after setup.

    Args:
        module_id: The unique byte-code identifier of the TTLModule instance. Since the mesoscope data acquisition
            pipeline uses multiple TTL modules on some microcontrollers, each instance running on the same
            microcontroller must have a unique identifier. The ID codes are not shared between AMC and other module
            types.
        report_pulses: A boolean flag that determines whether the class should report detecting HIGH signals to other
            processes. This is intended exclusively for the mesoscope frame acquisition recorder to notify the central
            process whether the mesoscope start trigger has been successfully received and processed by ScanImage
            software.
        debug: A boolean flag that configures the interface to dump certain data received from the microcontroller into
            the terminal. This is used during debugging and system calibration and should be disabled for most runtimes.

    Attributes:
        _report_pulses: Stores the report pulses flag.
        _debug: Stores the debug flag.
        _pulse_tracker: When the class is initialized with the report_pulses flag, it stores the SharedMemoryArray used
            to track how many pulses the class has recorded since initialization.
    """

    def __init__(self, module_id: np.uint8, report_pulses: bool = False, debug: bool = False) -> None:
        error_codes: set[np.uint8] = {np.uint8(51), np.uint8(54)}  # kOutputLocked, kInvalidPinMode
        # kInputOn, kInputOff, kOutputOn, kOutputOff
        # data_codes = {np.uint8(52), np.uint8(53), np.uint8(55), np.uint8(56)}

        self._debug: bool = debug
        self._report_pulses: bool = report_pulses

        # If the interface does not need to do any real-time processing of incoming data (not in debug or pulse
        # monitoring mode), so sets data_codes to None.
        data_codes: set[np.uint8] | None = None
        # If the interface runs in the debug mode, configures the interface to monitor all incoming data codes.
        if debug:
            data_codes = {np.uint8(52), np.uint8(53), np.uint8(55), np.uint8(56)}
        # Alternatively, if the interface is configured to report pulses, adds the HIGH phase code to the list of
        # monitored codes. We do not need to monitor other codes as pulse tracker simply counts how many pulses the
        # class has encountered, which uses rising edge.
        elif report_pulses:
            data_codes = {np.uint8(52)}

        super().__init__(
            module_type=np.uint8(1),
            module_id=module_id,
            mqtt_communication=False,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=error_codes,
        )

        # Precreates a shared memory array used to track and share the number of pulses encountered by the class with
        # other processes. Critically, for the class that monitors mesoscope frame timestamps, this is used to determine
        # if the mesoscope trigger successfully starts frame acquisition.
        self._pulse_tracker: SharedMemoryArray | None = None
        if self._report_pulses:
            self._pulse_tracker = SharedMemoryArray.create_array(
                name=f"{self._module_type}_{self._module_id}_pulse_tracker",
                prototype=np.zeros(shape=1, dtype=np.uint64),
                exist_ok=True,
            )

    def __del__(self) -> None:
        """Destroys the _pulse_tracker memory buffer and releases the resources reserved by the array during class
        runtime."""
        if self._pulse_tracker is not None:
            self._pulse_tracker.disconnect()
            self._pulse_tracker.destroy()

    def initialize_remote_assets(self) -> None:
        """If the class is instructed to report detected HIGH incoming pulses, connects to the _pulse_tracker
        SharedMemoryArray.
        """
        if self._pulse_tracker is not None:
            self._pulse_tracker.connect()

    def terminate_remote_assets(self) -> None:
        """If the class is instructed to report detected HIGH incoming pulses, disconnects from the _pulse_tracker
        SharedMemoryArray.
        """
        if self._pulse_tracker is not None:
            self._pulse_tracker.disconnect()

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """Processes incoming data when the class operates in debug or pulse reporting mode.

        During debug runtimes, this method dumps all received data into the terminal via the console class. During
        pulse reporting runtimes, the class increments the _pulse_tracker array each time it encounters a HIGH TTL
        signal edge sent by the mesoscope to timestamp acquiring (scanning) a new frame.

        Notes:
            If the interface runs in debug mode, make sure the console is enabled, as it is used to print received
            data into the terminal.
        """
        if self._debug:
            if message.event == 52:
                console.echo(f"TTLModule {self.module_id} detects HIGH signal")
            if message.event == 53:
                console.echo(f"TTLModule {self.module_id} detects LOW signal")
            if message.event == 55:
                console.echo(f"TTLModule {self.module_id} emits HIGH signal")
            if message.event == 56:
                console.echo(f"TTLModule {self.module_id} emits LOW signal")

        # If the class is running in the pulse tracking mode, each time the class receives a HIGH edge message,
        # increments the pulse tracker by one.
        if self._pulse_tracker is not None and message.event == 52:
            count = self._pulse_tracker.read_data(index=0, convert_output=False)
            count += 1
            self._pulse_tracker.write_data(index=0, data=count)

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(
        self, pulse_duration: np.uint32 = np.uint32(10000), averaging_pool_size: np.uint8 = np.uint8(0)
    ) -> None:
        """Changes the PC-addressable runtime parameters of the TTLModule instance.

        Use this method to package and apply new PC-addressable parameters to the TTLModule instance managed by
        this Interface class.

        Args:
            pulse_duration: The duration, in microseconds, of each emitted TTL pulse HIGH phase. This determines
                how long the TTL pin stays ON when emitting a pulse.
            averaging_pool_size: The number of digital pin readouts to average together when checking pin state. This
                is used during the execution of the check_state () command to debounce the pin readout and acts in
                addition to any built-in debouncing.
        """
        message = ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            parameter_data=(pulse_duration, averaging_pool_size),
        )
        self._input_queue.put(message)  # type: ignore

    def send_pulse(self, repetition_delay: np.uint32 = np.uint32(0), noblock: bool = True) -> None:
        """Triggers TTLModule to deliver a one-off or recurrent (repeating) digital TTL pulse.

        This command is well-suited to carry out most forms of TTL communication, but it is adapted for comparatively
        low-frequency communication at 10-200 Hz. This is in contrast to PWM outputs capable of mHz or even Khz pulse
        oscillation frequencies.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the command
                will only run once. The exact repetition delay will be further affected by other modules managed by the
                same microcontroller and may not be perfectly accurate.
            noblock: Determines whether the command should block the microcontroller while emitting the high phase of
                the pulse or not. Blocking ensures precise pulse duration, non-blocking allows the microcontroller to
                perform other operations while waiting, increasing its throughput.
        """
        command: OneOffModuleCommand | RepeatedModuleCommand
        if repetition_delay == 0:
            command = OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(noblock),
            )
        else:
            command = RepeatedModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(noblock),
                cycle_delay=repetition_delay,
            )

        self._input_queue.put(command)  # type: ignore

    def toggle(self, state: bool) -> None:
        """Triggers the TTLModule to continuously deliver a digital HIGH or LOW signal.

        This command locks the TTLModule managed by this Interface into delivering the desired logical signal.

        Args:
            state: The signal to output. Set to True for HIGH and False for LOW.
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(2 if state else 3),
            noblock=np.bool(False),
        )

        self._input_queue.put(command)  # type: ignore

    def check_state(self, repetition_delay: np.uint32 = np.uint32(0)) -> None:
        """Checks the state of the TTL signal received by the TTLModule.

        This command evaluates the state of the TTLModule's input pin and, if it is different from the previous state,
        reports it to the PC. This approach ensures that the module only reports signal level shifts (edges), preserving
        communication bandwidth.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the command
                will only run once.
        """
        command: OneOffModuleCommand | RepeatedModuleCommand
        if repetition_delay == 0:
            command = OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(4),
                noblock=np.bool(False),
            )
        else:
            command = RepeatedModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(4),
                noblock=np.bool(False),
                cycle_delay=repetition_delay,
            )
        self._input_queue.put(command)  # type: ignore

    @property
    def pulse_count(self) -> np.uint64:
        """Returns the total number of received TTL pulses recorded by the class since initialization."""
        if self._pulse_tracker is not None:
            return self._pulse_tracker.read_data(index=0, convert_output=False)  # type: ignore
        else:
            return _zero_uint  # If the array does not exist, always returns 0

    def reset_pulse_count(self) -> None:
        """Resets the tracked mesoscope pulse count to zero if the TTLInterface instance is used to monitor mesoscope
        frame acquisition pulses."""
        if self._pulse_tracker is not None:
            self._pulse_tracker.write_data(index=0, data=_zero_uint)


class BreakInterface(ModuleInterface):
    """Interfaces with BreakModule instances running on Ataraxis MicroControllers.

    BreakModule allows interfacing with a break to dynamically control the motion of break-coupled objects. The module
    is designed to send PWM signals that trigger Field-Effect-Transistor (FET) gated relay hardware to deliver voltage
    that variably engages the break. The module can be used to either fully engage or disengage the breaks or to output
    a PWM signal to engage the break with the desired strength.

    Notes:
        The break will notify the PC about its initial state (Engaged or Disengaged) after setup.

        This class is explicitly designed to work with an 8-bit Pulse Width Modulation (PWM) resolution. Specifically,
        it assumes that there are a total of 255 intervals covered by the whole PWM range when it calculates conversion
        factors to go from PWM levels to torque and force.

    Args:
        minimum_break_strength: The minimum torque applied by the break in gram centimeter. This is the torque the
            break delivers at minimum voltage (break is disabled).
        maximum_break_strength: The maximum torque applied by the break in gram centimeter. This is the torque the
            break delivers at maximum voltage (break is fully engaged).
        object_diameter: The diameter of the rotating object connected to the break, in centimeters. This is used to
            calculate the force at the end of the object associated with each torque level of the break.
        debug: A boolean flag that configures the interface to dump certain data received from the microcontroller into
            the terminal. This is used during debugging and system calibration and should be disabled for most runtimes.

    Attributes:
        _newton_per_gram_centimeter: Conversion factor from torque force in g cm to torque force in N cm.
        _minimum_break_strength: The minimum torque the break delivers at minimum voltage (break is disabled) in N cm.
        _maximum_break_strength: The maximum torque the break delivers at maximum voltage (break is fully engaged)
            in N cm.
        _torque_per_pwm: Conversion factor from break pwm levels to breaking torque in N cm.
        _force_per_pwm: Conversion factor from break pwm levels to breaking force in N at the edge of the object.
        _debug: Stores the debug flag.
    """

    def __init__(
        self,
        minimum_break_strength: float = 43.2047,  # 0.6 oz in
        maximum_break_strength: float = 1152.1246,  # 16 oz in
        object_diameter: float = 15.0333,
        debug: bool = False,
    ) -> None:
        error_codes: set[np.uint8] = {np.uint8(51)}  # kOutputLocked
        # data_codes = {np.uint8(52), np.uint8(53), np.uint8(54)}  # kEngaged, kDisengaged, kVariable

        self._debug: bool = debug

        # If the interface runs in the debug mode, configures the interface to monitor engaged and disengaged codes.
        data_codes: set[np.uint8] | None = None
        if debug:
            data_codes = {np.uint8(52), np.uint8(53)}

        # Initializes the subclassed ModuleInterface using the input instance data. Type data is hardcoded.
        super().__init__(
            module_type=np.uint8(3),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=error_codes,
        )

        # Hardcodes the conversion factor used to translate torque force in g cm to N cm
        self._newton_per_gram_centimeter: float = 0.00981

        # Converts minimum and maximum break strength into Newton centimeter
        self._minimum_break_strength: np.float64 = np.round(
            a=minimum_break_strength * self._newton_per_gram_centimeter,
            decimals=8,
        )
        self._maximum_break_strength: np.float64 = np.round(
            a=maximum_break_strength * self._newton_per_gram_centimeter,
            decimals=8,
        )

        # Computes the conversion factor to translate break pwm levels into breaking torque in Newtons cm. Rounds
        # to 12 decimal places for consistency and to ensure repeatability.
        self._torque_per_pwm: np.float64 = np.round(
            a=(self._maximum_break_strength - self._minimum_break_strength) / 255,
            decimals=8,
        )

        # Also computes the conversion factor to translate break pwm levels into force in Newtons. To overcome the
        # breaking torque, the object has to experience that much force applied to its edge.
        self._force_per_pwm: np.float64 = np.round(
            a=self._torque_per_pwm / (object_diameter / 2),
            decimals=8,
        )

    def initialize_remote_assets(self) -> None:
        """Not used."""
        pass

    def terminate_remote_assets(self) -> None:
        """Not used."""
        return

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """During debug runtime, dumps the data received from the module into the terminal.

        Currently, this method only works with codes 52 (Engaged) and 53 (Disengaged).

        Notes:
            The method is not used during non-debug runtimes. If the interface runs in debug mode, make sure the
            console is enabled, as it is used to print received data into the terminal.
        """
        # The method is ONLY called during debug runtime, so prints all received data via console.
        if message.event == 52:
            console.echo(f"Break is engaged")
        if message.event == 53:
            console.echo(f"Break is disengaged")

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(self, breaking_strength: np.uint8 = np.uint8(255)) -> None:
        """Changes the PC-addressable runtime parameters of the BreakModule instance.

        Use this method to package and apply new PC-addressable parameters to the BreakModule instance managed by this
        Interface class.

        Notes:
            Use set_breaking_power() command to apply the breaking-strength transmitted in this parameter message to the
            break. Until the command is called, the new breaking_strength will not be applied to the break hardware.

        Args:
            breaking_strength: The Pulse-Width-Modulation (PWM) value to use when the BreakModule delivers adjustable
                breaking power. Depending on this value, the breaking power can be adjusted from none (0) to maximum
                (255). Use get_pwm_from_force() to translate the desired breaking torque into the required PWM value.
        """
        message = ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),  # Generally, return code is only helpful for debugging.
            parameter_data=(breaking_strength,),
        )
        self._input_queue.put(message)  # type: ignore

    def toggle(self, state: bool) -> None:
        """Triggers the BreakModule to be permanently engaged at maximum strength or permanently disengaged.

        This command locks the BreakModule managed by this Interface into the desired state.

        Notes:
            This command does NOT use the breaking_strength parameter and always uses either maximum or minimum breaking
            power. To set the break to a specific torque level, set the level via the set_parameters() method and then
            switch the break into the variable torque mode by using the set_breaking_power() method.

        Args:
            state: The desired state of the break. True means the break is engaged; False means the break is disengaged.
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(1 if state else 2),
            noblock=np.bool(False),
        )
        self._input_queue.put(command)  # type: ignore

    def set_breaking_power(self) -> None:
        """Triggers the BreakModule to engage with the strength (torque) defined by the breaking_strength runtime
        parameter.

        Unlike the toggle() method, this method allows precisely controlling the torque applied by the break. This
        is achieved by pulsing the break control pin at the PWM level specified by breaking_strength runtime parameter
        stored in BreakModule's memory (on the microcontroller).

        Notes:
            This command switches the break to run in the variable strength mode and applies the current value of the
            breaking_strength parameter to the break, but it does not determine the breaking power. To adjust the power,
            use the set_parameters() class method to issue an updated breaking_strength value. By default, the break
            power is set to 50% (PWM value 128).
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(3),
            noblock=np.bool(False),
        )
        self._input_queue.put(command)  # type: ignore

    def get_pwm_from_torque(self, target_torque_n_cm: float) -> np.uint8:
        """Converts the desired breaking torque in Newtons centimeter to the required PWM value (0-255) to be delivered
        to the break hardware by the BreakModule.

        Use this method to convert the desired breaking torque into the PWM value that can be submitted to the
        BreakModule via the set_parameters() class method.

        Args:
            target_torque_n_cm: Desired torque in Newtons centimeter at the edge of the object.

        Returns:
            The byte PWM value that would generate the desired amount of torque.

        Raises:
            ValueError: If the input force is not within the valid range for the BreakModule.
        """
        if self._maximum_break_strength < target_torque_n_cm or self._minimum_break_strength > target_torque_n_cm:
            message = (
                f"The requested torque {target_torque_n_cm} N cm is outside the valid range for the BreakModule "
                f"{self._module_id}. Valid breaking torque range is from {self._minimum_break_strength} to "
                f"{self._maximum_break_strength}."
            )
            console.error(message=message, error=ValueError)

        # Calculates PWM using the pre-computed torque_per_pwm conversion factor
        pwm_value = np.uint8(round((target_torque_n_cm - self._minimum_break_strength) / self._torque_per_pwm))

        return pwm_value

    @property
    def torque_per_pwm(self) -> np.float64:
        """Returns the conversion factor to translate break pwm levels into breaking torque in Newton centimeters."""
        return self._torque_per_pwm

    @property
    def force_per_pwm(self) -> np.float64:
        """Returns the conversion factor to translate break pwm levels into breaking force in Newtons."""
        return self._force_per_pwm

    @property
    def maximum_break_strength(self) -> np.float64:
        """Returns the maximum torque of the break in Newton centimeters."""
        return self._maximum_break_strength

    @property
    def minimum_break_strength(self) -> np.float64:
        """Returns the minimum torque of the break in Newton centimeters."""
        return self._minimum_break_strength


class ValveInterface(ModuleInterface):
    """Interfaces with ValveModule instances running on Ataraxis MicroControllers.

    ValveModule allows interfacing with a solenoid valve to controllably dispense precise volumes of fluid. The module
    is designed to send digital signals that trigger Field-Effect-Transistor (FET) gated relay hardware to deliver
    voltage that opens or closes the controlled valve. The module can be used to either permanently open or close the
    valve or to cycle opening and closing in a way that ensures a specific amount of fluid passes through the
    valve.

    Notes:
        This interface comes pre-configured to receive valve pulse triggers from Unity via the "Gimbl/Reward/"
        topic.

        The valve will notify the PC about its initial state (Open or Closed) after setup.

        Our valve is statically configured to deliver audible tones when it is pulsed. This is used exclusively by the
        Pulse command, so the tone will not sound when the valve is activated during Calibration or Open commands. The
        default pulse duration is 100 ms, and this is primarily used to provide the animal with an auditory cue for the
        water reward.

    Args:
        valve_calibration_data: A tuple of tuples that contains the data required to map pulse duration to delivered
            fluid volume. Each sub-tuple should contain the integer that specifies the pulse duration in microseconds
            and a float that specifies the delivered fluid volume in microliters. If you do not know this data,
            initialize the class using a placeholder calibration tuple and use the calibration() class method to
            collect this data using the ValveModule.
        debug: A boolean flag that configures the interface to dump certain data received from the microcontroller into
            the terminal. This is used during debugging and system calibration and should be disabled for most runtimes.

    Attributes:
        _scale_coefficient: Stores the scale coefficient derived from the calibration data. We use the power law to
            fit the data, which results in better overall fit than using the linera equation.
        _nonlinearity_exponent: The intercept of the valve calibration curve. This is used to account for the fact that
            some valves may have a minimum open time or dispensed fluid volume, which is captured by the intercept.
            This improves the precision of fluid-volume-to-valve-open-time conversions.
        _calibration_cov: Stores the covariance matrix that describes the quality of fitting the calibration data using
            the power law. This is used to determine how well the valve performance is approximated by the power law.
        _reward_topic: Stores the topic used by Unity to issue reward commands to the module.
        _debug: Stores the debug flag.
        _valve_tracker: Stores the SharedMemoryArray that tracks the total volume of water dispensed by the valve
            during runtime.
        _previous_state: Tracks the previous valve state as Open (True) or Closed (False). This is used to accurately
            track delivered water volumes each time the valve opens and closes.
        _cycle_timer: A PrecisionTimer instance initialized in the Communication process to track how long the valve
            stays open during cycling. This is used together with the _previous_state to determine the volume of water
            delivered by the valve during runtime.
    """

    def __init__(
        self, valve_calibration_data: tuple[tuple[int | float, int | float], ...], debug: bool = False
    ) -> None:
        error_codes: set[np.uint8] = {np.uint8(51)}  # kOutputLocked
        # kOpen, kClosed, kCalibrated, kToneOn, kToneOff, kTonePinNotSet
        # data_codes = {np.uint8(52), np.uint8(53), np.uint8(54), np.uint8(55), np.uint8(56), np.uint8(57)}
        data_codes = {np.uint8(52), np.uint8(53), np.uint8(54)}  # kOpen, kClosed, kCalibrated

        self._debug: bool = debug

        # If the interface runs in the debug mode, expands the list of processed data codes to include all codes used
        # by the valve module.
        if debug:
            data_codes = {np.uint8(52), np.uint8(53), np.uint8(54)}

        super().__init__(
            module_type=np.uint8(5),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=error_codes,
        )

        # Extracts pulse durations and fluid volumes into separate arrays
        pulse_durations: NDArray[np.float64] = np.array([x[0] for x in valve_calibration_data], dtype=np.float64)
        fluid_volumes: NDArray[np.float64] = np.array([x[1] for x in valve_calibration_data], dtype=np.float64)

        # Defines the power-law model. Our calibration data suggests that the Valve performs in a non-linear fashion
        # and is better calibrated using the power law, rather than a linear fit
        def power_law_model(pulse_duration: Any, a: Any, b: Any, /) -> Any:
            return a * np.power(pulse_duration, b)

        # Fits the power-law model to the input calibration data and saves the fit parameters and covariance matrix to
        # class attributes
        # noinspection PyTupleAssignmentBalance
        params, fit_cov_matrix = curve_fit(f=power_law_model, xdata=pulse_durations, ydata=fluid_volumes)
        scale_coefficient, nonlinearity_exponent = params
        self._calibration_cov: NDArray[np.float64] = fit_cov_matrix
        self._scale_coefficient: np.float64 = np.round(a=np.float64(scale_coefficient), decimals=8)
        self._nonlinearity_exponent: np.float64 = np.round(a=np.float64(nonlinearity_exponent), decimals=8)

        # Stores the reward topic to make it accessible via property
        self._reward_topic: str = "Gimbl/Reward/"

        # Precreates a shared memory array used to track and share valve state data. Index 0 tracks the total amount of
        # water dispensed by the valve during runtime.
        self._valve_tracker: SharedMemoryArray = SharedMemoryArray.create_array(
            name=f"{self._module_type}_{self._module_id}_valve_tracker",
            prototype=np.zeros(shape=1, dtype=np.float64),
            exist_ok=True,
        )
        self._previous_state: bool = False
        self._cycle_timer: PrecisionTimer | None = None

    def __del__(self) -> None:
        """Ensures the reward_tracker is properly cleaned up when the class is garbage-collected."""
        self._valve_tracker.disconnect()
        self._valve_tracker.destroy()

    def initialize_remote_assets(self) -> None:
        """Connects to the reward tracker SharedMemoryArray and initializes the cycle PrecisionTimer from the
        Communication process."""
        self._valve_tracker.connect()
        self._cycle_timer = PrecisionTimer("us")

    def terminate_remote_assets(self) -> None:
        """Disconnects from the reward tracker SharedMemoryArray."""
        self._valve_tracker.disconnect()

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """Processes incoming data.

        Valve calibration events (code 54) are sent to the terminal via console regardless of the debug flag. If the
        class was initialized in the debug mode, Valve opening (code 52) and closing (code 53) codes are also sent to
        the terminal. Also, stores the total number of times the valve was opened under _reward_tracker index 0 and the
        total volume of water delivered during runtime under _reward_tracker index 1.

        Note:
            Make sure the console is enabled before calling this method.
        """
        if message.event == 52:
            if self._debug:
                console.echo(f"Valve Opened")

            # Resets the cycle timer each time the valve transitions to open state.
            if not self._previous_state:
                self._previous_state = True
                self._cycle_timer.reset()  # type: ignore

        elif message.event == 53:
            if self._debug:
                console.echo(f"Valve Closed")

            # Each time the valve transitions to closed state, records the period of time the valve was open and uses it
            # to estimate the volume of fluid delivered through the valve. Accumulates the total volume in the tracker
            # array.
            if self._previous_state:
                self._previous_state = False
                open_duration = self._cycle_timer.elapsed  # type: ignore

                # Accumulates delivered water volumes into the tracker.
                delivered_volume = np.float64(
                    self._scale_coefficient * np.power(open_duration, self._nonlinearity_exponent)
                )
                previous_volume = np.float64(self._valve_tracker.read_data(index=0, convert_output=False))
                new_volume = previous_volume + delivered_volume
                # noinspection PyTypeChecker
                self._valve_tracker.write_data(index=0, data=new_volume)
        elif message.event == 54:
            console.echo(f"Valve Calibration: Complete")

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(
        self,
        pulse_duration: np.uint32 = np.uint32(35590),
        calibration_delay: np.uint32 = np.uint32(200000),
        calibration_count: np.uint16 = np.uint16(200),
        tone_duration: np.uint32 = np.uint32(300000),
    ) -> None:
        """Changes the PC-addressable runtime parameters of the ValveModule instance.

        Use this method to package and apply new PC-addressable parameters to the ValveModule instance managed by this
        Interface class.

        Note:
            Default parameters are configured to support 'reference' calibration run. When calibrate() is called with
            these default parameters, the Valve should deliver ~5 uL of water, which is the value used during Sun lab
            experiments. If the reference calibration fails, you have to fully recalibrate the valve!

        Args:
            pulse_duration: The time, in microseconds, the valve stays open when it is pulsed (opened and closed). This
                is used during the execution of the send_pulse() command to control the amount of dispensed fluid. Use
                the get_duration_from_volume() method to convert the desired fluid volume into the pulse_duration value.
            calibration_delay: The time, in microseconds, to wait between consecutive pulses during calibration.
                Calibration works by repeatedly pulsing the valve the requested number of times. Delaying after closing
                the valve (ending the pulse) ensures the valve hardware has enough time to respond to the inactivation
                phase before starting the next calibration cycle.
            calibration_count: The number of times to pulse the valve during calibration. A number between 10 and 100 is
                enough for most use cases.
            tone_duration: The time, in microseconds, to sound the audible tone when the valve is pulsed. This is only
                used if the hardware ValveModule instance was provided with the TonePin argument at instantiation. If
                your use case involves emitting tones, make sure this value is higher than the pulse_duration value.
        """
        message = ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            parameter_data=(pulse_duration, calibration_delay, calibration_count, tone_duration),
        )
        self._input_queue.put(message)  # type: ignore

    def send_pulse(self, repetition_delay: np.uint32 = np.uint32(0), noblock: bool = False) -> None:
        """Triggers ValveModule to deliver a precise amount of fluid by cycling opening and closing the valve once or
        repetitively (recurrently).

        After calibration, this command allows delivering precise amounts of fluid with, depending on the used valve and
        relay hardware microliter or nanoliter precision. This command is optimized to change valve states at a
        comparatively low frequency in the 10-200 Hz range.

        Notes:
            To ensure the accuracy of fluid delivery, it is recommended to run the valve in the blocking mode
            and, if possible, isolate it to a controller that is not busy with running other tasks.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the command
                will only run once. The exact repetition delay will be further affected by other modules managed by the
                same microcontroller and may not be perfectly accurate.
            noblock: Determines whether the command should block the microcontroller while the valve is kept open.
                Blocking ensures precise pulse duration and dispensed fluid volume. Non-blocking allows the
                microcontroller to perform other operations while waiting, increasing its throughput.
        """
        command: OneOffModuleCommand | RepeatedModuleCommand
        if repetition_delay == 0:
            command = OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(noblock),
            )
        else:
            command = RepeatedModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(noblock),
                cycle_delay=repetition_delay,
            )
        self._input_queue.put(command)  # type: ignore

    def toggle(self, state: bool) -> None:
        """Triggers the ValveModule to be permanently open or closed.

        This command locks the ValveModule managed by this Interface into the desired state.

        Args:
            state: The desired state of the valve. True means the valve is open; False means the valve is closed.
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(2 if state else 3),
            noblock=np.bool(False),
        )
        self._input_queue.put(command)  # type: ignore

    def calibrate(self) -> None:
        """Triggers ValveModule to repeatedly pulse the valve using the duration defined by the pulse_duration runtime
        parameter.

        This command is used to build the calibration map of the valve that matches pulse_duration to the volume of
        fluid dispensed during the time the valve is open. To do so, the command repeatedly pulses the valve to dispense
        a large volume of fluid which can be measured and averaged to get the volume of fluid delivered during each
        pulse. The number of pulses carried out during this command is specified by the calibration_count parameter, and
        the delay between pulses is specified by the calibration_delay parameter.

        Notes:
            When activated, this command will block in-place until the calibration cycle is completed. Currently, there
            is no way to interrupt the command, and it may take a prolonged period of time (minutes) to complete.

            This command does not set any of the parameters involved in the calibration process. Make sure the
            parameters are submitted to the ValveModule's hardware memory via the set_parameters() class method before
            running the calibration() command.
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(4),
            noblock=np.bool(False),
        )
        self._input_queue.put(command)  # type: ignore

    def tone(self, repetition_delay: np.uint32 = np.uint32(0), noblock: bool = False) -> None:
        """Triggers ValveModule to an audible tone without changing the state of the managed valve.

        This command will only work for ValveModules connected to a piezoelectric buzzer and configured to interface
        with the buzzer's trigger pin. It allows emitting tones without water rewards, which is primarily used during
        training runtimes that pause delivering water when the animal is not consuming rewards.

        Notes:
            While enforcing auditory tone durations is not as important as enforcing valve open times, this command
            runs in blocking mode by default to match the behavior of the tone-emitting valve pulse command.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the command
                will only run once. The exact repetition delay will be further affected by other modules managed by the
                same microcontroller and may not be perfectly accurate.
            noblock: Determines whether the command should block the microcontroller while the tone is delivered.
                Blocking ensures precise tone duration. Non-blocking allows the microcontroller to perform other
                operations while waiting, increasing its throughput.
        """
        command: OneOffModuleCommand | RepeatedModuleCommand
        if repetition_delay == 0:
            command = OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(5),
                noblock=np.bool(noblock),
            )
        else:
            command = RepeatedModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(5),
                noblock=np.bool(noblock),
                cycle_delay=repetition_delay,
            )
        self._input_queue.put(command)  # type: ignore

    def get_duration_from_volume(self, target_volume: float) -> np.uint32:
        """Converts the desired fluid volume in microliters to the valve pulse duration in microseconds that ValveModule
        will use to deliver that fluid volume.

        Use this method to convert the desired fluid volume into the pulse_duration value that can be submitted to the
        ValveModule via the set_parameters() class method.

        Args:
            target_volume: Desired fluid volume in microliters.

        Raises:
            ValueError: If the desired fluid volume is too small to be reliably dispensed by the valve, based on its
                calibration data.

        Returns:
            The microsecond pulse duration that would be used to deliver the specified volume.
        """
        # Determines the minimum valid pulse duration. We hardcode this at 10 ms as this is the lower calibration
        # boundary
        min_pulse_duration = 10.0  # microseconds
        min_dispensed_volume = self._scale_coefficient * np.power(min_pulse_duration, self._nonlinearity_exponent)

        if target_volume < min_dispensed_volume:
            message = (
                f"The requested volume {target_volume} uL is too small to be reliably dispensed by the ValveModule "
                f"{self._module_id}. Specifically, the smallest volume of fluid the valve can reliably dispense is "
                f"{min_dispensed_volume} uL."
            )
            console.error(message=message, error=ValueError)

        # Inverts the power-law calibration to get the pulse duration.
        pulse_duration = (target_volume / self._scale_coefficient) ** (1.0 / self._nonlinearity_exponent)

        return np.uint32(np.round(pulse_duration))

    @property
    def mqtt_topic(self) -> str:
        """Returns the MQTT topic monitored by the module to receive reward commands from Unity."""
        return self._reward_topic

    @property
    def scale_coefficient(self) -> np.float64:
        """Returns the scaling coefficient (A) from the power‐law calibration.

        In the calibration model, fluid_volume = A * (pulse_duration)^B, this coefficient
        converts pulse duration (in microseconds) into the appropriate fluid volume (in microliters)
        when used together with the nonlinearity exponent.
        """
        return self._scale_coefficient

    @property
    def nonlinearity_exponent(self) -> np.float64:
        """Returns the nonlinearity exponent (B) from the power‐law calibration.

        In the calibration model, fluid_volume = A * (pulse_duration)^B, this exponent indicates
        the degree of nonlinearity in how the dispensed volume scales with the valve’s pulse duration.
        For example, an exponent of 1 would indicate a linear relationship.
        """
        return self._nonlinearity_exponent

    @property
    def calibration_covariance(self) -> NDArray[np.float64]:
        """Returns the 2x2 covariance matrix associated with the power‐law calibration fit.

        The covariance matrix contains the estimated variances of the calibration parameters
        on its diagonal (i.e., variance of the scale coefficient and the nonlinearity exponent)
        and the covariances between these parameters in its off-diagonal elements.

        This information can be used to assess the uncertainty in the calibration.

        Returns:
            A NumPy array (2x2) representing the covariance matrix.
        """
        return self._calibration_cov

    @property
    def delivered_volume(self) -> np.float64:
        """Returns the total volume of water, in microliters, delivered by the valve during the current runtime."""
        return self._valve_tracker.read_data(index=0, convert_output=False)  # type: ignore

    @property
    def valve_tracker(self) -> SharedMemoryArray:
        """Returns the SharedMemoryArray that stores the total number of valve pulses and the total volume of water
        delivered during the current runtime.

        The number of valve pulses is stored under index 0, while the total delivered volume is stored under index 1.
        Both values are stored as a float64 datatype. The total delivered volume is given in microliters.
        """
        return self._valve_tracker


class LickInterface(ModuleInterface):
    """Interfaces with LickModule instances running on Ataraxis MicroControllers.

    LickModule allows interfacing with conductive lick sensors used in the Sun Lab to detect mouse interaction with
    water dispensing tubes. The sensor works by sending a small direct current through the mouse, which is picked up by
    the sensor connected to the metal lick tube. When the mouse completes the circuit by making the contact with the
    tube, the sensor determines whether the resultant voltage matches the threshold expected for a tongue contact and,
    if so, notifies the PC about the contact.

    Notes:
        The sensor is calibrated to work with very small currents that are not detectable by the animal, so it does not
        interfere with behavior during experiments. The sensor will, however, interfere with electrophysiological
        recordings.

        The resolution of the sensor is high enough to distinguish licks from paw touches. By default, the
        microcontroller is configured in a way that will likely send both licks and non-lick interactions to the PC.
        Use the lick_threshold argument to provide a more exclusive lick threshold.

        The interface automatically sends significant lick triggers to Unity via the "LickPort/" MQTT topic. This only
        includes the 'onset' triggers, the interface does not report voltage level reductions (associated with the end
        of the tongue-to-tube contact).

    Args:
        lick_threshold: The threshold voltage, in raw analog units recorded by a 12-bit ADC, for detecting the tongue
            contact. Note, 12-bit ADC only supports values between 0 and 4095, so setting the threshold above 4095 will
            result in no licks being reported to Unity.
        debug: A boolean flag that configures the interface to dump certain data received from the microcontroller into
            the terminal. This is used during debugging and system calibration and should be disabled for most runtimes.

    Attributes:
        _sensor_topic: Stores the output MQTT topic.
        _lick_threshold: The threshold voltage for detecting a tongue contact.
        _volt_per_adc_unit: The conversion factor to translate the raw analog values recorded by the 12-bit ADC into
            voltage in Volts.
        _debug: Stores the debug flag.
        _lick_tracker: Stores the SharedMemoryArray that stores the current lick detection status and the total number
            of licks detected since class initialization.
        _previous_readout_zero: Stores a boolean indicator of whether the previous voltage readout was a 0-value.
    """

    def __init__(self, lick_threshold: int = 1000, debug: bool = False) -> None:
        data_codes: set[np.uint8] = {np.uint8(51)}  # kChanged
        self._debug: bool = debug

        # Initializes the subclassed ModuleInterface using the input instance data. Type data is hardcoded.
        super().__init__(
            module_type=np.uint8(4),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=None,
        )

        self._sensor_topic: str = "LickPort/"
        self._lick_threshold: np.uint16 = np.uint16(lick_threshold)

        # Statically computes the voltage resolution of each analog step, assuming a 3.3V ADC with 12-bit resolution.
        self._volt_per_adc_unit: np.float64 = np.round(a=np.float64(3.3 / (2**12)), decimals=8)

        # Precreates a shared memory array used to track and share the total number of licks recorded by the sensor
        # since class initialization.
        self._lick_tracker: SharedMemoryArray = SharedMemoryArray.create_array(
            name=f"{self._module_type}_{self._module_id}_lick_tracker",
            prototype=np.zeros(shape=1, dtype=np.uint64),
            exist_ok=True,
        )

        # Precreates storage variables used to prevent excessive lick reporting
        self._previous_readout_zero: bool = False

    def __del__(self) -> None:
        """Ensures the lick_tracker is properly cleaned up when the class is garbage-collected."""
        self._lick_tracker.disconnect()
        self._lick_tracker.destroy()

    def initialize_remote_assets(self) -> None:
        """Connects to the SharedMemoryArray used to communicate lick status to other processes."""
        self._lick_tracker.connect()

    def terminate_remote_assets(self) -> None:
        """Disconnects from the lick-tracker SharedMemoryArray."""
        self._lick_tracker.disconnect()  # Does not destroy the array to support start / stop cycling.

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """Processes incoming data.

        Lick data (code 51) comes in as a change in the voltage level detected by the sensor pin. This value is then
        evaluated against the _lick_threshold, and if the value exceeds the threshold, a binary lick trigger is sent to
        Unity via MQTT. Additionally, the method increments the total lick count stored in the _lick_tracker each time
        an above-threshold voltage readout is received from the module.

        Notes:
            If the class runs in debug mode, this method sends all received lick sensor voltages to the
            terminal via console. Make sure the console is enabled before calling this method.
        """

        # Currently, only code 51 messages will be passed to this method. From each, extracts the detected voltage
        # level.
        detected_voltage: np.uint16 = message.data_object  # type: ignore

        # If the class is initialized in debug mode, prints each received voltage level to the terminal.
        if self._debug:
            console.echo(f"Lick ADC signal: {detected_voltage}")

        # Since the sensor is pulled to 0 to indicate lack of tongue contact, a zero-readout necessarily means no
        # lick. Sets zero-tracker to 1 to indicate that a zero-state has been encountered
        if detected_voltage == 0:
            self._previous_readout_zero = True
            return

        # If the voltage level exceeds the lick threshold and this is the first time the threshold is exceeded since
        # the last zero-value, reports it to Unity via MQTT. Threshold is inclusive. This exploits the fact that every
        # pair of licks has to be separated by a zero-value (lack of tongue contact). So, to properly report the licks,
        # only does it once per encountering a zero-value.
        if detected_voltage >= self._lick_threshold and self._previous_readout_zero:
            # Increments the lick count and updates the tracker array with new data
            count = self._lick_tracker.read_data(index=0, convert_output=False)
            count += 1
            self._lick_tracker.write_data(index=0, data=count)

            # This disables further reports until the sensor sends a zero-value again
            self._previous_readout_zero = False

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(
        self,
        signal_threshold: np.uint16 = np.uint16(200),
        delta_threshold: np.uint16 = np.uint16(180),
        averaging_pool_size: np.uint8 = np.uint8(30),
    ) -> None:
        """Changes the PC-addressable runtime parameters of the LickModule instance.

        Use this method to package and apply new PC-addressable parameters to the LickModule instance managed by this
        Interface class.

        Notes:
            All threshold parameters are inclusive! If you need help determining appropriate threshold levels for
            specific targeted voltages, use the get_adc_units_from_volts() method of the interface instance.

        Args:
            signal_threshold: The minimum voltage level, in raw analog units of 12-bit Analog-to-Digital-Converter
                (ADC), that needs to be reported to the PC. Setting this threshold to a number above zero allows
                high-pass filtering the incoming signals. Note, Signals below the threshold will be pulled to 0.
            delta_threshold: The minimum value by which the signal has to change, relative to the previous check, for
                the change to be reported to the PC. Note, if the change is 0, the signal will not be reported to the
                PC, regardless of this parameter value.
            averaging_pool_size: The number of analog pin readouts to average together when checking pin state. This
                is used to smooth the recorded values to avoid communication line noise. Teensy microcontrollers have
                built-in analog pin averaging, but we disable it by default and use this averaging method instead. It is
                recommended to set this value between 15 and 30 readouts.
        """
        message = ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),  # Generally, return code is only helpful for debugging.
            parameter_data=(signal_threshold, delta_threshold, averaging_pool_size),
        )
        self._input_queue.put(message)  # type: ignore

    def check_state(self, repetition_delay: np.uint32 = np.uint32(0)) -> None:
        """Returns the voltage signal detected by the analog pin monitored by the LickModule.

        If there has been a significant change in the detected voltage level and the level is within the reporting
        thresholds, reports the change to the PC. It is highly advised to issue this command to repeat (recur) at a
        desired interval to continuously monitor the lick sensor state, rather than repeatedly calling it as a one-off
        command for best runtime efficiency.

        This command allows continuously monitoring the mouse interaction with the lickport tube. It is designed
        to return the raw analog units, measured by a 3.3V ADC with 12-bit resolution. To avoid floating-point math, the
        value is returned as an unsigned 16-bit integer.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the
            command will only run once.
        """
        command: OneOffModuleCommand | RepeatedModuleCommand
        if repetition_delay == 0:
            command = OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
            )

        else:
            command = RepeatedModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
                cycle_delay=repetition_delay,
            )
        self._input_queue.put(command)  # type: ignore

    def get_adc_units_from_volts(self, voltage: float) -> np.uint16:
        """Converts the input voltage to raw analog units of 12-bit Analog-to-Digital-Converter (ADC).

        Use this method to determine the appropriate raw analog units for the threshold arguments of the
        set_parameters() method, based on the desired voltage thresholds.

        Notes:
            This method assumes a 3.3V ADC with 12-bit resolution.

        Args:
            voltage: The voltage to convert to raw analog units, in Volts.

        Returns:
            The raw analog units of 12-bit ADC for the input voltage.
        """
        return np.uint16(np.round(voltage / self._volt_per_adc_unit))

    @property
    def mqtt_topic(self) -> str:
        """Returns the MQTT topic used to transfer lick events from the interface to Unity."""
        return self._sensor_topic

    @property
    def volts_per_adc_unit(self) -> np.float64:
        """Returns the conversion factor to translate the raw analog values recorded by the 12-bit ADC into voltage in
        Volts.
        """
        return self._volt_per_adc_unit

    @property
    def lick_count(self) -> np.uint64:
        """Returns the total number of licks detected by the module since runtime onset."""
        return self._lick_tracker.read_data(index=0, convert_output=False)  # type: ignore

    @property
    def lick_threshold(self) -> np.uint16:
        """Returns the voltage threshold, in raw ADC units of a 12-bit Analog-to-Digital voltage converter that is
        interpreted as the mouse licking the sensor."""
        return self._lick_threshold


class TorqueInterface(ModuleInterface):
    """Interfaces with TorqueModule instances running on Ataraxis MicroControllers.

    TorqueModule interfaces with a differential torque sensor. The sensor uses differential coding in the millivolt
    range to communicate torque in the CW and the CCW direction. To convert and amplify the output of the torque sensor,
    it is wired to an AD620 microvolt amplifier instrument that converts the output signal into a single positive
    vector and amplifies its strength to Volts range.

    The TorqueModule further refines the sensor data by ensuring that CCW and CW torque signals behave identically.
    Specifically, it adjusts the signal to scale from 0 to baseline proportionally to the detected torque, regardless
    of torque direction.

    Notes:
        This interface receives torque as a positive uint16_t value from zero to at most 2046 raw analog units of 3.3v
        12-bit ADC converter. The direction of the torque is reported by the event-code of the received message.

    Args:
        baseline_voltage: The voltage level, in raw analog units measured by 3.3v ADC at 12-bit resolution after the
            AD620 amplifier, that corresponds to no (0) torque readout. Usually, for a 3.3v ADC, this would be around
            2046 (the midpoint, ~1.65 V).
        maximum_voltage: The voltage level, in raw analog units measured by 3.3v ADC at 12-bit resolution after the
            AD620 amplifier, that corresponds to the absolute maximum torque detectable by the sensor. The best way
            to get this value is to measure the positive voltage level after applying the maximum CW (positive) torque.
            At most, this value can be 4095 (~3.3 V).
        sensor_capacity: The maximum torque detectable by the sensor, in grams centimeter (g cm).
        object_diameter: The diameter of the rotating object connected to the torque sensor, in centimeters. This is
            used to calculate the force at the edge of the object associated with the measured torque at the sensor.
        debug: A boolean flag that configures the interface to dump certain data received from the microcontroller into
            the terminal. This is used during debugging and system calibration and should be disabled for most runtimes.

    Attributes:
        _newton_per_gram_centimeter: Stores the hardcoded conversion factor from gram centimeter to Newton centimeter.
        _capacity_in_newtons_cm: The maximum torque detectable by the sensor in Newtons centimeter.
        _torque_per_adc_unit: The conversion factor to translate raw analog 3.3v 12-bit ADC values to torque in Newtons
            centimeter.
        _force_per_adc_unit: The conversion factor to translate raw analog 3.3v 12-bit ADC values to force in Newtons.
        _debug: Stores the debug flag.
    """

    def __init__(
        self,
        baseline_voltage: int = 2046,
        maximum_voltage: int = 2750,
        sensor_capacity: float = 720.0779,  # 10 oz in
        object_diameter: float = 15.0333,
        debug: bool = False,
    ) -> None:
        self._debug: bool = debug
        # data_codes = {np.uint8(51), np.uint8(52)}  # kCCWTorque, kCWTorque

        # If the interface runs in the debug mode, configures it to monitor and report detected torque values
        data_codes: set[np.uint8] | None = None
        if debug:
            data_codes = {np.uint8(51), np.uint8(52)}

        # Initializes the subclassed ModuleInterface using the input instance data. Type data is hardcoded.
        super().__init__(
            module_type=np.uint8(6),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=None,
        )

        # Hardcodes the conversion factor used to translate torque in g cm to N cm
        self._newton_per_gram_centimeter: np.float64 = np.float64(0.00981)

        # Determines the capacity of the torque sensor in Newtons centimeter.
        self._capacity_in_newtons_cm: np.float64 = np.round(
            a=np.float64(sensor_capacity) * self._newton_per_gram_centimeter,
            decimals=8,
        )

        # Computes the conversion factor to translate the recorded raw analog readouts of the 3.3V 12-bit ADC to
        # torque in Newton centimeter. Rounds to 12 decimal places for consistency and to ensure
        # repeatability.
        self._torque_per_adc_unit: np.float64 = np.round(
            a=(self._capacity_in_newtons_cm / (maximum_voltage - baseline_voltage)),
            decimals=8,
        )

        # Also computes the conversion factor to translate the recorded raw analog readouts of the 3.3V 12-bit ADC to
        # force in Newtons.
        self._force_per_adc_unit: np.float64 = np.round(
            a=self._torque_per_adc_unit / (object_diameter / 2),
            decimals=8,
        )

    def initialize_remote_assets(self) -> None:
        """Not used."""
        return

    def terminate_remote_assets(self) -> None:
        """Not used."""
        return

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """If the class is initialized in debug mode, prints the received torque data to the terminal via console.

        In debug mode, this method parses incoming code 51 (CW torque) and code 52 (CCW torque) data and dumps it into
         the terminal via console. If the class is not initialized in debug mode, this method does nothing.

        Notes:
            Make sure the console is enabled before calling this method.
        """
        # This is here to appease mypy, currently all message inputs are ModuleData messages
        if isinstance(message, ModuleState):
            return

        # The torque direction is encoded via the message event code. CW torque (code 52) is interpreted as negative
        # and CCW (code 51) as positive.
        sign = 1 if message.event == np.uint8(51) else -1

        # Translates the absolute torque into the CW / CCW vector and converts from raw ADC units to Newton centimeters
        # using the precomputed conversion factor. Uses float64 and rounds to 8 decimal places for consistency and
        # precision
        signed_torque = np.round(
            a=np.float64(message.data_object) * self._torque_per_adc_unit * sign,
            decimals=8,
        )

        # Since this method is only called in the debug mode, always prints the data to the console
        console.echo(message=f"Torque: {signed_torque} N cm, ADC: {np.int32(message.data_object) * sign}.")

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(
        self,
        report_ccw: np.bool = np.bool(True),
        report_cw: np.bool = np.bool(True),
        signal_threshold: np.uint16 = np.uint16(100),
        delta_threshold: np.uint16 = np.uint16(70),
        averaging_pool_size: np.uint8 = np.uint8(10),
    ) -> None:
        """Changes the PC-addressable runtime parameters of the TorqueModule instance.

        Use this method to package and apply new PC-addressable parameters to the TorqueModule instance managed by this
        Interface class.

        Notes:
            All threshold parameters are inclusive! If you need help determining appropriate threshold levels for
            specific targeted torque levels, use the get_adc_units_from_torque() method of the interface instance.

        Args:
            report_ccw: Determines whether the sensor should report torque in the CounterClockwise (CCW) direction.
            report_cw: Determines whether the sensor should report torque in the Clockwise (CW) direction.
            signal_threshold: The minimum torque level, in raw analog units of 12-bit Analog-to-Digital-Converter
                (ADC), that needs to be reported to the PC. Setting this threshold to a number above zero allows
                high-pass filtering the incoming signals. Note, Signals below the threshold will be pulled to 0.
            delta_threshold: The minimum value by which the signal has to change, relative to the previous check, for
                the change to be reported to the PC. Note, if the change is 0, the signal will not be reported to the
                PC, regardless of this parameter value.
            averaging_pool_size: The number of analog pin readouts to average together when checking pin state. This
                is used to smooth the recorded values to avoid communication line noise. Teensy microcontrollers have
                built-in analog pin averaging, but we disable it by default and use this averaging method instead. It is
                recommended to set this value between 15 and 30 readouts.
        """
        message = ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),  # Generally, return code is only helpful for debugging.
            parameter_data=(
                report_ccw,
                report_cw,
                signal_threshold,
                delta_threshold,
                averaging_pool_size,
            ),
        )
        self._input_queue.put(message)  # type: ignore

    def check_state(self, repetition_delay: np.uint32 = np.uint32(0)) -> None:
        """Returns the torque signal detected by the analog pin monitored by the TorqueModule.

        If there has been a significant change in the detected signal (voltage) level and the level is within the
        reporting thresholds, reports the change to the PC. It is highly advised to issue this command to repeat
        (recur) at a desired interval to continuously monitor the lick sensor state, rather than repeatedly calling it
        as a one-off command for best runtime efficiency.

        This command allows continuously monitoring the CW and CCW torque experienced by the object connected to the
        torque sensor. It is designed to return the raw analog units, measured by a 3.3V ADC with 12-bit resolution.
        To avoid floating-point math, the value is returned as an unsigned 16-bit integer.

        Notes:
            Due to how the torque signal is measured and processed, the returned value will always be between 0 and
            the baseline ADC value. For a 3.3V 12-bit ADC, this is between 0 and ~1.65 Volts.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the
            command will only run once.
        """
        command: OneOffModuleCommand | RepeatedModuleCommand
        if repetition_delay == 0:
            command = OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
            )
        else:
            command = RepeatedModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
                cycle_delay=repetition_delay,
            )
        self._input_queue.put(command)  # type: ignore

    def get_adc_units_from_torque(self, target_torque: float) -> np.uint16:
        """Converts the input torque to raw analog units of 12-bit Analog-to-Digital-Converter (ADC).

        Use this method to determine the appropriate raw analog units for the threshold arguments of the
        set_parameters() method.

        Notes:
            This method assumes a 3.3V ADC with 12-bit resolution.

        Args:
            target_torque: The target torque in Newton centimeter, to convert to an ADC threshold.

        Returns:
            The raw analog units of 12-bit ADC for the input torque.
        """
        return np.uint16(np.round(target_torque / self._torque_per_adc_unit))

    @property
    def torque_per_adc_unit(self) -> np.float64:
        """Returns the conversion factor to translate the raw analog values recorded by the 12-bit ADC into torque in
        Newton centimeter.
        """
        return self._torque_per_adc_unit

    @property
    def force_per_adc_unit(self) -> np.float64:
        """Returns the conversion factor to translate the raw analog values recorded by the 12-bit ADC into force in
        Newtons.
        """
        return self._force_per_adc_unit


class ScreenInterface(ModuleInterface):
    """Interfaces with ScreenModule instances running on Ataraxis MicroControllers.

    ScreenModule is specifically designed to interface with the HDMI converter boards used in Sun lab's Virtual Reality
    setup. The ScreenModule communicates with the boards to toggle the screen displays on and off, without interfering
    with their setup on the host PC.

    Notes:
        Since the current VR setup uses three screens, this implementation of ScreenModule is designed to interface
        with all three screens at the same time. In the future, the module may be refactored to allow addressing
        individual screens.

        The physical wiring of the module also allows manual screen manipulation via the buttons on the control panel
        if the ScreenModule is not actively delivering a toggle pulse. However, changing the state of the screen
        manually is strongly discouraged, as it interferes with tracking the state of the screen via software.

    Args:
        initially_on: A boolean flag that communicates the initial state of the screen. This is used during log parsing
            to deduce the state of the screen after each toggle pulse and assumes the screens are only manipulated via
            this interface.
        debug: A boolean flag that configures the interface to dump certain data received from the microcontroller into
            the terminal. This is used during debugging and system calibration and should be disabled for most runtimes.

    Attributes:
        _initially_on: Stores the initial state of the screens.
        _debug: Stores the debug flag.
    """

    def __init__(self, initially_on: bool, debug: bool = False) -> None:
        error_codes: set[np.uint8] = {np.uint8(51)}  # kOutputLocked

        self._debug: bool = debug
        self._initially_on: bool = initially_on

        # kOn, kOff
        # data_codes = {np.uint8(52), np.uint8(53)}

        # If the interface runs in the debug mode, configures the interface to monitor relay On / Off codes.
        data_codes: set[np.uint8] | None = None
        if debug:
            data_codes = {np.uint8(52), np.uint8(53)}

        super().__init__(
            module_type=np.uint8(7),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=error_codes,
        )

    def initialize_remote_assets(self) -> None:
        """Not used."""
        pass

    def terminate_remote_assets(self) -> None:
        """Not used."""
        pass

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """If the class runs in the debug mode, dumps the received data into the terminal via console class.

        This method is only used in the debug mode to print Screen toggle signal HIGH (On) and LOW (Off) phases.

        Notes:
            This method uses the console to print the data to the terminal. Make sure it is enabled before calling this
            method.
        """
        if message.event == 52:
            console.echo(f"Screen toggle: HIGH")
        if message.event == 53:
            console.echo(f"Screen toggle: LOW")

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(self, pulse_duration: np.uint32 = np.uint32(1000000)) -> None:
        """Changes the PC-addressable runtime parameters of the ScreenModule instance.

        Use this method to package and apply new PC-addressable parameters to the ScreenModule instance managed by
        this Interface class.

        Args:
            pulse_duration: The duration, in microseconds, of each emitted screen toggle pulse HIGH phase. This is
                equivalent to the duration of the control panel POWER button press. The main criterion for this
                parameter is to be long enough for the converter board to register the press.
        """
        message = ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            parameter_data=(pulse_duration,),
        )
        self._input_queue.put(message)  # type: ignore

    def toggle(self) -> None:
        """Triggers the ScreenModule to briefly simulate pressing the POWER button of the scree control board.

        This command is used to turn the connected display on or off. The new state of the display depends on the
        current state of the display when the command is issued. Since the displays can also be controlled manually
        (via the physical control board buttons), the state of the display can also be changed outside this interface,
        although it is highly advised to NOT change screen states manually.

        Notes:
            It is highly recommended to use this command to manipulate display states, as it ensures that display state
            changes are logged for further data analysis.
        """
        command = OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(1),
            noblock=np.bool(False),
        )
        self._input_queue.put(command)  # type: ignore

    @property
    def initially_on(self) -> bool:
        """Returns True if the screens were initially ON when the module interface was initialized, False otherwise."""
        return self._initially_on
