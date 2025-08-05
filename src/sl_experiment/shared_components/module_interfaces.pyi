import numpy as np
from _typeshed import Incomplete
from numpy.typing import NDArray as NDArray
from ataraxis_time import PrecisionTimer
from ataraxis_data_structures import SharedMemoryArray
from ataraxis_communication_interface import ModuleData, ModuleState, ModuleInterface

_zero_uint: Incomplete
_zero_float: Incomplete

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

    _motion_topic: str
    _ppr: int
    _object_diameter: float
    _debug: bool
    _cm_per_pulse: np.float64
    _unity_unit_per_pulse: np.float64
    _distance_tracker: SharedMemoryArray
    def __init__(
        self,
        encoder_ppr: int = 8192,
        object_diameter: float = 15.0333,
        cm_per_unity_unit: float = 10.0,
        debug: bool = False,
    ) -> None: ...
    def __del__(self) -> None:
        """Ensures the speed_tracker is properly cleaned up when the class is garbage-collected."""
    def initialize_remote_assets(self) -> None:
        """Connects to the speed_tracker SharedMemoryArray."""
    def terminate_remote_assets(self) -> None:
        """Disconnects from the speed_tracker SharedMemoryArray."""
    def process_received_data(self, message: ModuleState | ModuleData) -> None:
        """Processes incoming data in real time.

        Motion data (codes 51 and 52) is converted into CW / CCW vectors, translated from pulses to Unity units, and
        is sent to Unity via MQTT. Encoder PPR data (code 53) is printed via the console.

        Also, keeps track of the total distance traveled by the animal since class initialization, relative to the
        initial position at runtime onset and updates the distance_tracker SharedMemoryArray.

        Notes:
            If debug mode is enabled, motion data is also converted to centimeters and printed via the console.
        """
    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
    def set_parameters(
        self, report_ccw: np.bool | bool = ..., report_cw: np.bool | bool = ..., delta_threshold: np.uint32 | int = ...
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
    def check_state(self, repetition_delay: np.uint32 = ...) -> None:
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
    def reset_pulse_count(self) -> None:
        """Resets the EncoderModule pulse tracker to 0.

        This command allows resetting the encoder without evaluating its current pulse count. Currently, this command
        is designed to only run once.
        """
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
    @property
    def mqtt_topic(self) -> str:
        """Returns the MQTT topic used to transfer motion data from the interface to Unity."""
    @property
    def cm_per_pulse(self) -> np.float64:
        """Returns the conversion factor to translate raw encoder pulse count to distance moved in centimeters."""
    @property
    def absolute_position(self) -> np.float64:
        """Returns the absolute position of the animal relative to the runtime onset in Unity units.

        The position is given relative to the position at runtime onset ('0').
        """
    @property
    def traveled_distance(self) -> np.float64:
        """Returns the total distance, in centimeters, traveled by the animal since runtime onset.

        This distance tracker is a monotonically incrementing count of traversed centimeters that does not account for
        the direction of travel.
        """
    def reset_distance_tracker(self) -> None:
        """Resets the array that tracks the total traveled distance and the absolute position of the animal relative to
        the runtime onset.
        """

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

    _debug: bool
    _report_pulses: bool
    _pulse_tracker: SharedMemoryArray | None
    def __init__(self, module_id: np.uint8, report_pulses: bool = False, debug: bool = False) -> None: ...
    def __del__(self) -> None:
        """Destroys the _pulse_tracker memory buffer and releases the resources reserved by the array during class
        runtime."""
    def initialize_remote_assets(self) -> None:
        """If the class is instructed to report detected HIGH incoming pulses, connects to the _pulse_tracker
        SharedMemoryArray.
        """
    def terminate_remote_assets(self) -> None:
        """If the class is instructed to report detected HIGH incoming pulses, disconnects from the _pulse_tracker
        SharedMemoryArray.
        """
    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """Processes incoming data when the class operates in debug or pulse reporting mode.

        During debug runtimes, this method dumps all received data into the terminal via the console class. During
        pulse reporting runtimes, the class increments the _pulse_tracker array each time it encounters a HIGH TTL
        signal edge sent by the mesoscope to timestamp acquiring (scanning) a new frame.

        Notes:
            If the interface runs in debug mode, make sure the console is enabled, as it is used to print received
            data into the terminal.
        """
    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
    def set_parameters(self, pulse_duration: np.uint32 = ..., averaging_pool_size: np.uint8 = ...) -> None:
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
    def send_pulse(self, repetition_delay: np.uint32 = ..., noblock: bool = True) -> None:
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
    def toggle(self, state: bool) -> None:
        """Triggers the TTLModule to continuously deliver a digital HIGH or LOW signal.

        This command locks the TTLModule managed by this Interface into delivering the desired logical signal.

        Args:
            state: The signal to output. Set to True for HIGH and False for LOW.
        """
    def check_state(self, repetition_delay: np.uint32 = ...) -> None:
        """Checks the state of the TTL signal received by the TTLModule.

        This command evaluates the state of the TTLModule's input pin and, if it is different from the previous state,
        reports it to the PC. This approach ensures that the module only reports signal level shifts (edges), preserving
        communication bandwidth.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the command
                will only run once.
        """
    @property
    def pulse_count(self) -> np.uint64:
        """Returns the total number of received TTL pulses recorded by the class since initialization."""
    def reset_pulse_count(self) -> None:
        """Resets the tracked mesoscope pulse count to zero if the TTLInterface instance is used to monitor mesoscope
        frame acquisition pulses."""

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

    _debug: bool
    _newton_per_gram_centimeter: float
    _minimum_break_strength: np.float64
    _maximum_break_strength: np.float64
    _torque_per_pwm: np.float64
    _force_per_pwm: np.float64
    def __init__(
        self,
        minimum_break_strength: float = 43.2047,
        maximum_break_strength: float = 1152.1246,
        object_diameter: float = 15.0333,
        debug: bool = False,
    ) -> None: ...
    def initialize_remote_assets(self) -> None:
        """Not used."""
    def terminate_remote_assets(self) -> None:
        """Not used."""
    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """During debug runtime, dumps the data received from the module into the terminal.

        Currently, this method only works with codes 52 (Engaged) and 53 (Disengaged).

        Notes:
            The method is not used during non-debug runtimes. If the interface runs in debug mode, make sure the
            console is enabled, as it is used to print received data into the terminal.
        """
    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
    def set_parameters(self, breaking_strength: np.uint8 = ...) -> None:
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
    @property
    def torque_per_pwm(self) -> np.float64:
        """Returns the conversion factor to translate break pwm levels into breaking torque in Newton centimeters."""
    @property
    def force_per_pwm(self) -> np.float64:
        """Returns the conversion factor to translate break pwm levels into breaking force in Newtons."""
    @property
    def maximum_break_strength(self) -> np.float64:
        """Returns the maximum torque of the break in Newton centimeters."""
    @property
    def minimum_break_strength(self) -> np.float64:
        """Returns the minimum torque of the break in Newton centimeters."""

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

    _debug: bool
    _calibration_cov: NDArray[np.float64]
    _scale_coefficient: np.float64
    _nonlinearity_exponent: np.float64
    _reward_topic: str
    _valve_tracker: SharedMemoryArray
    _previous_state: bool
    _cycle_timer: PrecisionTimer | None
    def __init__(
        self, valve_calibration_data: tuple[tuple[int | float, int | float], ...], debug: bool = False
    ) -> None: ...
    def __del__(self) -> None:
        """Ensures the reward_tracker is properly cleaned up when the class is garbage-collected."""
    def initialize_remote_assets(self) -> None:
        """Connects to the reward tracker SharedMemoryArray and initializes the cycle PrecisionTimer from the
        Communication process."""
    def terminate_remote_assets(self) -> None:
        """Disconnects from the reward tracker SharedMemoryArray."""
    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """Processes incoming data.

        Valve calibration events (code 54) are sent to the terminal via console regardless of the debug flag. If the
        class was initialized in the debug mode, Valve opening (code 52) and closing (code 53) codes are also sent to
        the terminal. Also, stores the total number of times the valve was opened under _reward_tracker index 0 and the
        total volume of water delivered during runtime under _reward_tracker index 1.

        Note:
            Make sure the console is enabled before calling this method.
        """
    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
    def set_parameters(
        self,
        pulse_duration: np.uint32 = ...,
        calibration_delay: np.uint32 = ...,
        calibration_count: np.uint16 = ...,
        tone_duration: np.uint32 = ...,
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
    def send_pulse(self, repetition_delay: np.uint32 = ..., noblock: bool = False) -> None:
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
    def toggle(self, state: bool) -> None:
        """Triggers the ValveModule to be permanently open or closed.

        This command locks the ValveModule managed by this Interface into the desired state.

        Args:
            state: The desired state of the valve. True means the valve is open; False means the valve is closed.
        """
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
    def tone(self, repetition_delay: np.uint32 = ..., noblock: bool = False) -> None:
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
    @property
    def mqtt_topic(self) -> str:
        """Returns the MQTT topic monitored by the module to receive reward commands from Unity."""
    @property
    def scale_coefficient(self) -> np.float64:
        """Returns the scaling coefficient (A) from the power‐law calibration.

        In the calibration model, fluid_volume = A * (pulse_duration)^B, this coefficient
        converts pulse duration (in microseconds) into the appropriate fluid volume (in microliters)
        when used together with the nonlinearity exponent.
        """
    @property
    def nonlinearity_exponent(self) -> np.float64:
        """Returns the nonlinearity exponent (B) from the power‐law calibration.

        In the calibration model, fluid_volume = A * (pulse_duration)^B, this exponent indicates
        the degree of nonlinearity in how the dispensed volume scales with the valve’s pulse duration.
        For example, an exponent of 1 would indicate a linear relationship.
        """
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
    @property
    def delivered_volume(self) -> np.float64:
        """Returns the total volume of water, in microliters, delivered by the valve during the current runtime."""
    @property
    def valve_tracker(self) -> SharedMemoryArray:
        """Returns the SharedMemoryArray that stores the total number of valve pulses and the total volume of water
        delivered during the current runtime.

        The number of valve pulses is stored under index 0, while the total delivered volume is stored under index 1.
        Both values are stored as a float64 datatype. The total delivered volume is given in microliters.
        """

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
        includes the \'onset\' triggers, the interface does not report voltage level reductions (associated with the end
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

    _debug: bool
    _sensor_topic: str
    _lick_threshold: np.uint16
    _volt_per_adc_unit: np.float64
    _lick_tracker: SharedMemoryArray
    _previous_readout_zero: bool
    def __init__(self, lick_threshold: int = 1000, debug: bool = False) -> None: ...
    def __del__(self) -> None:
        """Ensures the lick_tracker is properly cleaned up when the class is garbage-collected."""
    def initialize_remote_assets(self) -> None:
        """Connects to the SharedMemoryArray used to communicate lick status to other processes."""
    def terminate_remote_assets(self) -> None:
        """Disconnects from the lick-tracker SharedMemoryArray."""
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
    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
    def set_parameters(
        self, signal_threshold: np.uint16 = ..., delta_threshold: np.uint16 = ..., averaging_pool_size: np.uint8 = ...
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
    def check_state(self, repetition_delay: np.uint32 = ...) -> None:
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
    @property
    def mqtt_topic(self) -> str:
        """Returns the MQTT topic used to transfer lick events from the interface to Unity."""
    @property
    def volts_per_adc_unit(self) -> np.float64:
        """Returns the conversion factor to translate the raw analog values recorded by the 12-bit ADC into voltage in
        Volts.
        """
    @property
    def lick_count(self) -> np.uint64:
        """Returns the total number of licks detected by the module since runtime onset."""
    @property
    def lick_threshold(self) -> np.uint16:
        """Returns the voltage threshold, in raw ADC units of a 12-bit Analog-to-Digital voltage converter that is
        interpreted as the mouse licking the sensor."""

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

    _debug: bool
    _newton_per_gram_centimeter: np.float64
    _capacity_in_newtons_cm: np.float64
    _torque_per_adc_unit: np.float64
    _force_per_adc_unit: np.float64
    def __init__(
        self,
        baseline_voltage: int = 2046,
        maximum_voltage: int = 2750,
        sensor_capacity: float = 720.0779,
        object_diameter: float = 15.0333,
        debug: bool = False,
    ) -> None: ...
    def initialize_remote_assets(self) -> None:
        """Not used."""
    def terminate_remote_assets(self) -> None:
        """Not used."""
    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """If the class is initialized in debug mode, prints the received torque data to the terminal via console.

        In debug mode, this method parses incoming code 51 (CW torque) and code 52 (CCW torque) data and dumps it into
         the terminal via console. If the class is not initialized in debug mode, this method does nothing.

        Notes:
            Make sure the console is enabled before calling this method.
        """
    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
    def set_parameters(
        self,
        report_ccw: np.bool = ...,
        report_cw: np.bool = ...,
        signal_threshold: np.uint16 = ...,
        delta_threshold: np.uint16 = ...,
        averaging_pool_size: np.uint8 = ...,
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
    def check_state(self, repetition_delay: np.uint32 = ...) -> None:
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
    @property
    def torque_per_adc_unit(self) -> np.float64:
        """Returns the conversion factor to translate the raw analog values recorded by the 12-bit ADC into torque in
        Newton centimeter.
        """
    @property
    def force_per_adc_unit(self) -> np.float64:
        """Returns the conversion factor to translate the raw analog values recorded by the 12-bit ADC into force in
        Newtons.
        """

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

    _debug: bool
    _initially_on: bool
    def __init__(self, initially_on: bool, debug: bool = False) -> None: ...
    def initialize_remote_assets(self) -> None:
        """Not used."""
    def terminate_remote_assets(self) -> None:
        """Not used."""
    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """If the class runs in the debug mode, dumps the received data into the terminal via console class.

        This method is only used in the debug mode to print Screen toggle signal HIGH (On) and LOW (Off) phases.

        Notes:
            This method uses the console to print the data to the terminal. Make sure it is enabled before calling this
            method.
        """
    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
    def set_parameters(self, pulse_duration: np.uint32 = ...) -> None:
        """Changes the PC-addressable runtime parameters of the ScreenModule instance.

        Use this method to package and apply new PC-addressable parameters to the ScreenModule instance managed by
        this Interface class.

        Args:
            pulse_duration: The duration, in microseconds, of each emitted screen toggle pulse HIGH phase. This is
                equivalent to the duration of the control panel POWER button press. The main criterion for this
                parameter is to be long enough for the converter board to register the press.
        """
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
    @property
    def initially_on(self) -> bool:
        """Returns True if the screens were initially ON when the module interface was initialized, False otherwise."""
