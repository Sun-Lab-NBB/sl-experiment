"""This module provides ModuleInterface implementations for the hardware used by the Sun lab VR-Mesoscope system."""

from json import dumps
import math
from multiprocessing import Queue as MPQueue
from multiprocessing import Manager
from multiprocessing.managers import SyncManager

import numpy as np
from ataraxis_data_structures.shared_memory.shared_memory_array import SharedMemoryArray
from numpy.typing import NDArray
from ataraxis_base_utilities import console
from numpy.polynomial.polynomial import polyfit
from ataraxis_communication_interface import (
    ModuleData,
    ModuleState,
    ModuleInterface,
    ModuleParameters,
    MQTTCommunication,
    OneOffModuleCommand,
    RepeatedModuleCommand,
)
from typing import Any


class EncoderInterface(ModuleInterface):
    """Interfaces with EncoderModule instances running on Ataraxis MicroControllers.

    EncoderModule allows interfacing with quadrature encoders used to monitor the direction and magnitude of connected
    object's rotation. To achieve the highest resolution, the module relies on hardware interrupt pins to detect and
    handle the pulses sent by the two encoder channels.

    Notes:
        This interface sends CW and CCW motion data to Unity via 'LinearTreadmill/Data' MQTT topic.

        The default initial encoder readout is 0 (no CW or CCW motion). The class instance is zeroed at communication
        initialization.

    Args:
        encoder_ppr: The resolution of the managed quadrature encoder, in Pulses Per Revolution (PPR). This is the
            number of quadrature pulses the encoder emits per full 360-degree rotation. If this number is not known,
            provide a placeholder value and use get_ppr() command to estimate the PPR using the index channel of the
            encoder.
        object_diameter: The diameter of the rotating object connected to the encoder, in centimeters. This is used to
            convert encoder pulses into rotated distance in cm.
        cm_per_unity_unit: The conversion factor to translate the distance traveled by the edge of the connected object
             into Unity units. This value works together with object_diameter and encoder_ppr to translate raw
             encoder pulses received from the microcontroller into Unity-compatible units.

    Attributes:
        _motion_topic: Stores the MQTT motion topic.
        _ppr: Stores the resolution of the managed quadrature encoder.
        _object_diameter: Stores the diameter of the object connected to the encoder.
        _cm_per_unity_unit: Stores the conversion factor that translates centimeters into Unity units.
        _unity_unit_per_pulse: Stores the conversion factor to translate encoder pulses into Unity units.
        _communication: Stores the communication class used to send data to Unity over MQTT.
        _mp_manager: Stores the multiprocessing manager used for managing the output multiprocessing queue.
        _output_queue: Stores the multiprocessing queue used to send data from the communication process back to the
            main process.
    """

    def __init__(
        self,
        encoder_ppr: int = 8192,
        object_diameter: float = 15.0333,  # 0333 is to account for the wheel wrap
        cm_per_unity_unit: float = 10.0,
    ) -> None:
        self._mp_manager: SyncManager = Manager()
        data_codes = {np.uint8(51), np.uint8(52), np.uint8(53)}  # kRotatedCCW, kRotatedCW, kPPR

        super().__init__(
            module_type=np.uint8(2),
            module_id=np.uint8(1),
            mqtt_communication=True,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=None,
        )

        # Saves additional data to class attributes.
        self._motion_topic = "LinearTreadmill/Data"  # Hardcoded output topic
        self._ppr = encoder_ppr
        self._object_diameter = object_diameter
        self._cm_per_unity_unit = cm_per_unity_unit

        # Computes the conversion factor to translate encoder pulses into unity units. Rounds to 8 decimal places for
        # consistency and to ensure repeatability.
        self._unity_unit_per_pulse = np.round(
            a=np.float64((math.pi * object_diameter) / (encoder_ppr * cm_per_unity_unit)),
            decimals=8,
        )

        # The communication class used to send data to Unity over MQTT. Initializes to a placeholder due to pickling
        # issues
        self._communication: MQTTCommunication | None = None

        # The queue used to output PPR reports to the main process
        self._output_queue: MPQueue = self._mp_manager.Queue()

    def initialize_remote_assets(self):
        self._communication = MQTTCommunication()
        self._communication.connect()

    def terminate_remote_assets(self):
        self._communication.disconnect()

    def process_received_data(self, message: ModuleState | ModuleData) -> None:
        # If the incoming message is the PPR report, sends the data to the output queue
        if message.event == 53:
            ppr = message.data_object
            self._output_queue.put(ppr)

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

        # Encodes the motion data into the format expected by the GIMBL Unity module and serializes it into a
        # byte-string.
        json_string = dumps(obj={"movement": signed_motion})
        byte_array = json_string.encode("utf-8")

        # Publishes the motion to the appropriate MQTT topic.
        self._communication.send_data(topic=self._motion_topic, payload=byte_array)  # type: ignore

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

    def check_state(self, repetition_delay: np.uint32 = np.uint32(0)) -> None:
        """Returns the number of pulses accumulated by the EncoderModule since the last check or reset.

        If there has been a significant change in the absolute count of pulses, reports the change and direction to the
        PC. It is highly advised to issue this command to repeat (recur) at a desired interval to continuously monitor
        the encoder state, rather than repeatedly calling it as a one-off command for best runtime efficiency.

        This command allows continuously monitoring the rotation of the object connected to the encoder. It is designed
        to return the absolute raw count of pulses emitted by the encoder in response to the object ration. This allows
        avoiding floating-point arithmetic on the microcontroller and relies on the PC to convert pulses to standard
        units,s uch as centimeters. The specific conversion algorithm depends on the encoder and motion diameter.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the
            command will only run once.
        """
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
        """Returns the conversion factor to translate raw encoder pulse count to real world centimeters of motion."""
        return np.round(
            a=np.float64((math.pi * self._object_diameter) / self._ppr),
            decimals=8,
        )

    @property
    def output_queue(self) -> MPQueue:  # type: ignore
        """Returns the multiprocessing queue used to transfer the ppr values from the communication process to the main
        process.
        """
        return self._output_queue

    def parse_logged_data(self) -> tuple[NDArray[np.uint64], NDArray[np.float64]]:
        """Extracts and converts the encoder displacement logged during runtime into absolute position of the animal in
        centimeters.

        This method should be called during data preprocessing carried out at the end of each experimental session to
        prepare encoder data for alignment with other experimental data sources and integration into the unified VR
        behavior dataset.

        Returns:
            A tuple with two elements. The first element is a numpy array that stores the timestamps in microseconds
            elapsed since UTC epoch onset. The second element is a numpy array that stores the absolute position of the
            animal in centimeters at each timestamp.
        """
        # Reads the data logged during runtime as a dictionary of dictionaries.
        log_data: dict[Any, list[dict[str, Any]]] = self.extract_logged_data()

        # Precreates the lists to store extracted data
        timestamps = []
        displacements = []

        # Top level keys in the returned dictionary are event codes. We look for codes 51 and 52. 51 is the code for
        # CCW rotation, 52 is the code for CW rotation.
        for value in log_data[np.uint8(51)]:
            timestamps.append(value["timestamp"])
            displacements.append(value["data"])  # CCW rotation is interpreted as the positive direction
        for value in log_data[np.uint8(52)]:
            timestamps.append(value["timestamp"])
            displacements.append(-value["data"])  # CW rotation is interpreted as the negative direction

        # Converts lists to numpy arrays (for efficiency) and sorts by timestamp to get the correct sequence of
        # displacements as they occurred during the experiment.
        timestamps = np.array(timestamps, dtype=np.uint64)
        displacements = np.array(displacements, dtype=np.float64)
        sort_idx = np.argsort(timestamps)
        timestamps = timestamps[sort_idx]
        displacements = displacements[sort_idx]

        # Converts displacements to absolute positions using the cumulative sum and translates from encoder pulses to
        # centimeters
        positions = np.round(np.cumsum(displacements) * self.cm_per_pulse, decimals=8)

        # Returns sorted timestamps and the absolute position of the encoder at each timestamp.
        return timestamps, positions


class TTLInterface(ModuleInterface):
    """Interfaces with TTLModule instances running on Ataraxis MicroControllers.

    TTLModule facilitates exchanging Transistor-to-Transistor Logic (TTL) signals between various hardware systems, such
    as microcontrollers, cameras and recording devices. The module contains methods for both sending and receiving TTL
    pulses, but each TTLModule instance can only perform one of these functions at a time.

    Notes:
        When the TTLModule is configured to output a signal, it will notify the PC about the initial signal state
        (HIGH or LOW) after setup.

    Attributes:
        _input_flag: A one-element SharedMemoryArray used to communicate to other processes when the interfaced
            TTLModule first receives a HIGH input signal.
        _once: A boolean flag that ensures that the _input_flag is flipped from 0 to 1 exactly once.

    """

    def __init__(self, module_id: np.uint8) -> None:
        error_codes = {np.uint8(51), np.uint8(54)}  # kOutputLocked, kInvalidPinMode

        # kInputOn, kInputOff, kOutputOn, kOutputOff
        # data_codes = {np.uint8(52), np.uint8(53), np.uint8(55), np.uint8(56)}

        # HIGH incoming pulses are used to detect when other equipment is operational. For example, when mesoscope
        # sends HIGH frame acquisition triggers, this is used to notify the main process tha the mesoscope has been
        # armed and is now acquiring images.
        data_codes = {np.uint8(52)}

        super().__init__(
            module_type=np.uint8(1),
            module_id=module_id,
            mqtt_communication=False,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=error_codes,
        )

        # Initializes the shared memory array used to share whether the interface has received an InputOn code from the
        # microcontroller with other processes.
        prototype = np.zeros(shape=1, dtype=np.uint8)
        self._input_flag = SharedMemoryArray.create_array(
            name=f"1_{module_id}_flag", prototype=prototype, exist_ok=True
        )

        # This attribute is used to ensure that the _input_flag is flipped from 0 to 1 exactly once.
        self._once = True

    def initialize_remote_assets(self):
        self._input_flag.connect()

    def terminate_remote_assets(self):
        self._input_flag.disconnect()
        self._input_flag.destroy()

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        # The only messages that reach this method are messages with event_code 52. The first time this happens, flips
        # the value of the _input_flag. In turns, th central process uses this flag to detect when external equipment,
        # such as the mesoscope, is armed and ready to record experimental data.
        if self._once:
            # noinspection PyTypeChecker
            self._input_flag.write_data(index=0, data=1)

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
                is used during the execution of check_state() command to debounce the pin readout and acts in addition
                to any built-in debouncing.
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
        low-frequency communication at 10-200 Hz. This is in-contrast to PWM outputs capable of mHz or even Khz pulse
        oscillation frequencies.

        Args:
            repetition_delay: The time, in microseconds, to delay before repeating the command. If set to 0, the command
                will only run once. The exact repetition delay will be further affected by other modules managed by the
                same microcontroller and may not be perfectly accurate.
            noblock: Determines whether the command should block the microcontroller while emitting the high phase of
                the pulse or not. Blocking ensures precise pulse duration, non-blocking allows the microcontroller to
                perform other operations while waiting, increasing its throughput.
        """
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

    def parse_logged_data(self) -> tuple[NDArray[np.uint64], NDArray[np.float64]]:
        """Extracts and converts the encoder displacement logged during runtime into absolute position of the animal in
        centimeters.

        This method should be called during data preprocessing carried out at the end of each experimental session to
        prepare encoder data for alignment with other experimental data sources and integration into the unified VR
        behavior dataset.

        Returns:
            A tuple with two elements. The first element is a numpy array that stores the timestamps in microseconds
            elapsed since UTC epoch onset. The second element is a numpy array that stores the absolute position of the
            animal in centimeters at each timestamp.
        """
        # Reads the data logged during runtime as a dictionary of dictionaries.
        log_data: dict[Any, list[dict[str, Any]]] = self.extract_logged_data()


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

    Attributes:
        _newton_per_gram_centimeter: Conversion factor from torque force in g cm to torque force in N cm.
        _minimum_break_strength: The minimum torque the break delivers at minimum voltage (break is disabled) in N cm.
        _maximum_break_strength: The maximum torque the break delivers at maximum voltage (break is fully engaged) in N
            cm.
        _torque_per_pwm: Conversion factor from break pwm levels to breaking torque in N cm.
        _force_per_pwm: Conversion factor from break pwm levels to breaking force in N at the edge of the object.
    """

    def __init__(
        self,
        minimum_break_strength: float = 43.2047,  # 0.6 in iz
        maximum_break_strength: float = 1152.1246,  # 16 in oz
        object_diameter: float = 15.0333,
    ) -> None:
        error_codes = {np.uint8(51)}  # kOutputLocked
        # data_codes = {np.uint8(52), np.uint8(53), np.uint8(54)}  # kEngaged, kDisengaged, kVariable

        # Initializes the subclassed ModuleInterface using the input instance data. Type data is hardcoded.
        super().__init__(
            module_type=np.uint8(3),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=None,  # None of the data codes need additional processing, so set to None.
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
        self._torque_per_pwm = np.round(
            a=(self._maximum_break_strength - self._minimum_break_strength) / 255,
            decimals=8,
        )

        # Also computes the conversion factor to translate break pwm levels into force in Newtons. TO overcome the
        # breaking torque, the object has to experience that much force applied to its edge.
        self._force_per_pwm = np.round(
            a=self._torque_per_pwm / (object_diameter / 2),
            decimals=8,
        )

    def process_received_data(self, message: ModuleData | ModuleState) -> None:
        """Not used."""
        return

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(self, breaking_strength: np.uint8 = np.uint8(255)) -> ModuleParameters:
        """Changes the PC-addressable runtime parameters of the BreakModule instance.

        Use this method to package and apply new PC-addressable parameters to the BreakModule instance managed by this
        Interface class.

        Notes:
            Use set_breaking_power() command to apply the breaking-strength transmitted in this parameter message to the
            break. Until the command is called, the new breaking_strength will not be applied to the break hardware.

        Args:
            breaking_strength: The Pulse-Width-Modulation (PWM) value to use when the BreakModule delivers adjustable
                breaking power. Depending on this value, the breaking power can be adjusted from none (0) to maximum
                (255). Use get_pwm_from_force() to translate desired breaking torque into the required PWM value.

        Returns:
            The ModuleParameters message that can be sent to the microcontroller via the send_message() method of
            the MicroControllerInterface class.
        """
        return ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),  # Generally, return code is only helpful for debugging.
            parameter_data=(breaking_strength,),
        )

    def toggle(self, state: bool) -> OneOffModuleCommand:
        """Triggers the BreakModule to be permanently engaged at maximum strength or permanently disengaged.

        This command locks the BreakModule managed by this Interface into the desired state.

        Notes:
            This command does NOT use the breaking_strength parameter and always uses either maximum or minimum breaking
            power. To set the break to a specific torque level, set the level via the set_parameters() method and then
            switch the break into the variable torque mode by using the set_breaking_power() method.

        Args:
            state: The desired state of the break. True means the break is engaged; False means the break is disengaged.

        Returns:
            The OneOffModuleCommand message that can be sent to the microcontroller via the send_message() method of the
            MicroControllerInterface class.
        """
        return OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(1 if state else 2),
            noblock=np.bool(False),
        )

    def set_breaking_power(self) -> OneOffModuleCommand:
        """Triggers the BreakModule to engage with the strength (torque) defined by the breaking_strength runtime
        parameter.

        Unlike the toggle() method, this method allows precisely controlling the torque applied by the break. This
        is achieved by pulsing the break control pin at the PWM level specified by breaking_strength runtime parameter
        stored in BreakModule's memory (on the microcontroller).

        Notes:
            This command switches the break to run in the variable strength mode and applies the current value of the
            breaking_strength parameter to the break, but it does not determine the breaking power. To adjust the power,
            use the set_parameters() class method to issue updated breaking_strength value. By default, the break power
            is set to 50% (PWM value 128).

        Returns:
            The OneOffModuleCommand message that can be sent to the microcontroller via the send_message() method of the
            MicroControllerInterface class.
        """
        return OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(3),
            noblock=np.bool(False),
        )

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


class ValveInterface(ModuleInterface):
    """Interfaces with ValveModule instances running on Ataraxis MicroControllers.

    ValveModule allows interfacing with a solenoid valve to controllably dispense precise amounts of fluid. The module
    is designed to send digital signals that trigger Field-Effect-Transistor (FET) gated relay hardware to deliver
    voltage that opens or closes the controlled valve. The module can be used to either permanently open or close the
    valve or to cycle opening and closing in a way that ensures a specific amount of fluid passes through the
    valve.

    Notes:
        This interface comes pre-configured to receive valve pulse triggers from Unity via the "Gimbl/Reward/"
        topic.

        The valve will notify the PC about its initial state (Open or Closed) after setup.

    Args:
        valve_calibration_data: A tuple of tuples that contains the data required to map pulse duration to delivered
            fluid volume. Each sub-tuple should contain the integer that specifies the pulse duration in microseconds
            and a float that specifies the delivered fluid volume in microliters. If you do not know this data,
            initialize the class using a placeholder calibration tuple and use calibration() class method to collect
            this data using the ValveModule.

    Attributes:
        _microliters_per_microsecond: The conversion factor that maps the valve open time, in microseconds, to the
            volume of dispensed fluid, in microliters.
        _intercept; The intercept of the valve calibration curve. This is used to account for the fact that some valves
            may have a minimum open time or dispensed fluid volume, which is captured by the intercept. This improves
            the precision of fluid-volume-to-valve-open-time conversions.
        _reward_topic: Stores the topic used by Unity to issue reward commands to the module.
    """

    def __init__(self, valve_calibration_data: tuple[tuple[int | float, int | float], ...]) -> None:
        error_codes = {np.uint8(51)}  # kOutputLocked
        # data_codes = {np.uint8(52), np.uint8(53), np.uint8(54)}  # kOpen, kClosed, kCalibrated
        data_codes = {np.uint8(54)}  # The only code that requires additional processing is kCalibrated
        mqtt_command_topics = {"Gimbl/Reward/"}

        super().__init__(
            module_type=np.uint8(5),
            module_id=np.uint8(1),
            mqtt_communication=True,
            data_codes=data_codes,
            mqtt_command_topics=mqtt_command_topics,
            error_codes=error_codes,
        )

        # Extracts pulse durations and fluid volumes into separate arrays
        pulse_durations: NDArray[np.float64] = np.array([x[0] for x in valve_calibration_data], dtype=np.float64)
        fluid_volumes: NDArray[np.float64] = np.array([x[1] for x in valve_calibration_data], dtype=np.float64)

        # Computes the conversion factor by finding the slope and the intercept of the calibration curve.
        slope: np.float64
        intercept: np.float64
        slope, intercept = polyfit(pulse_durations, fluid_volumes, deg=1)
        self._microliters_per_microsecond: np.float64 = np.round(a=slope, decimals=8)
        self._intercept: np.float64 = np.round(a=intercept, decimals=8)

        # Stores the reward topic separately to make it accessible via property
        self._reward_topic = "Gimbl/Reward/"

    def process_received_data(
        self,
        message: ModuleData | ModuleState,
        mqtt_communication: MQTTCommunication,
        mp_queue: MPQueue,  # type: ignore
    ) -> None:
        # Since the only data code that requires further processing is code 54 (kCalibrated), this method statically
        # puts 'calibrated' into the queue as a one-element tuple.
        if message.event == 54:
            mp_queue.put(("Calibrated",))

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> OneOffModuleCommand:
        # If the received message was sent to the reward topic, this is a binary (empty payload) trigger to
        # pulse the valve. It is expected that the valve parameters are configured so that this delivers the
        # desired amount of water reward.
        if topic == self._reward_topic:
            return OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),  # Blocks to ensure reward delivery precision.
            )

    def set_parameters(
        self,
        pulse_duration: np.uint32 = np.uint32(10000),
        calibration_delay: np.uint32 = np.uint32(10000),
        calibration_count: np.uint16 = np.uint16(100),
    ) -> ModuleParameters:
        """Changes the PC-addressable runtime parameters of the ValveModule instance.

        Use this method to package and apply new PC-addressable parameters to the ValveModule instance managed by this
        Interface class.

        Args:
            pulse_duration: The time, in microseconds, the valve stays open when it is pulsed (opened and closed). This
                is used during the execution of send_pulse() command to control the amount of dispensed fluid. Use
                get_duration_from_volume() method to convert the desired fluid volume into the pulse_duration value.
            calibration_delay: The time, in microseconds, to wait between consecutive pulses during calibration.
                Calibration works by repeatedly pulsing the valve the requested number of times. Delaying after closing
                the valve (ending the pulse) ensures the valve hardware has enough time to respond to the inactivation
                phase before starting the next calibration cycle.
            calibration_count: The number of times to pulse the valve during calibration. A number between 10 and 100 is
                enough for most use cases.

        Returns:
            The ModuleParameters message that can be sent to the microcontroller via the send_message() method of
            the MicroControllerInterface class.
        """
        return ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            parameter_data=(pulse_duration, calibration_delay, calibration_count),
        )

    def send_pulse(
        self, repetition_delay: np.uint32 = np.uint32(0), noblock: bool = False
    ) -> RepeatedModuleCommand | OneOffModuleCommand:
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
            noblock: Determines whether the command should block the microcontroller while the valve is kept open or
                not. Blocking ensures precise pulse duration and, by extension, delivered fluid volume. Non-blocking
                allows the microcontroller to perform other operations while waiting, increasing its throughput.

        Returns:
            The RepeatedModuleCommand or OneOffModuleCommand message that can be sent to the microcontroller via the
            send_message() method of the MicroControllerInterface class.
        """
        if repetition_delay == 0:
            return OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(noblock),
            )

        return RepeatedModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(1),
            noblock=np.bool(noblock),
            cycle_delay=repetition_delay,
        )

    def toggle(self, state: bool) -> OneOffModuleCommand:
        """Triggers the ValveModule to be permanently open or closed.

        This command locks the ValveModule managed by this Interface into the desired state.

        Args:
            state: The desired state of the valve. True means the valve is open; False means the valve is closed.

        Returns:
            The OneOffModuleCommand message that can be sent to the microcontroller via the send_message() method of the
            MicroControllerInterface class.
        """
        return OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(2 if state else 3),
            noblock=np.bool(False),
        )

    def calibrate(self) -> OneOffModuleCommand:
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

        Returns:
            The OneOffModuleCommand message that can be sent to the microcontroller via the send_message() method of
            the MicroControllerInterface class.
        """
        return OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(4),
            noblock=np.bool(False),
        )

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
        if target_volume < self._intercept:
            message = (
                f"The requested volume {target_volume} uL is too small to be reliably dispensed by the ValveModule "
                f"{self._module_id}. Specifically, the smallest volume of fluid the valve can reliably dispense is "
                f"{self._intercept} uL."
            )
            console.error(message=message, error=ValueError)
        return np.uint32(np.round(target_volume / self._microliters_per_microsecond + self._intercept))

    @property
    def mqtt_topic(self) -> str:
        """Returns the MQTT topic monitored by the module to receive reward commands from Unity."""
        return self._reward_topic

    @property
    def microliter_per_microsecond(self) -> np.float64:
        """Returns the conversion factor to translate valve open time, in microseconds, into the volume of dispensed
        fluid, in microliters.
        """
        return self._microliters_per_microsecond

    @property
    def minimum_dispensed_volume(self) -> np.float64:
        """Returns the minimum volume that the valve can reliably dispense."""
        return self._intercept


class LickInterface(ModuleInterface):
    """Interfaces with LickModule instances running on Ataraxis MicroControllers.

    LickModule allows interfacing with conductive lick sensors used in the Sun Lab to detect mouse interaction with
    water dispensing tubes. The sensor works by sending a small direct current through the mouse, which is picked up by
    the sensor connected to the metal lick tube. When the mouse completes the circuit by making the contact with the
    tube, the sensor determines whether the resultant voltage matches the threshold expected for a torque contact and,
    if so, notifies the PC about the contact.

    Notes:
        The sensor is calibrated to work with very small currents the animal does not detect, so it does not interfere
        with behavior during experiments. The sensor will, however, interfere with electrophysiological recordings.

        The resolution of the sensor is high enough to distinguish licks from paw touches. By default, the
        microcontroller is configured in a way that will likely send both licks and non-lick interactions to the PC.
        Use lick_threshold argument to provide a more exclusive lick threshold.

        The interface automatically sends significant lick triggers to Unity via the "LickPort/" MQTT topic. This only
        includes the 'onset' triggers, the interface does not report voltage level reductions (associated with the end
        of the mouse-to-tube contact).

        The default state of the sensor after setup or reset is 0. Until the sensor sends a state message communicating
        a non-zero detected value, it can be safely assumed that the sensor detects the voltage of 0.

    Args:
        lick_threshold: The threshold voltage, in raw analog units recorded by a 12-bit ADC, for detecting the torque
            contact. Note, 12-bit ADC only supports values between 0 and 4095, so setting the threshold above 4095 will
            result in no licks being reported to Unity.

    Attributes:
        _sensor_topic: Stores the output MQTT topic.
        _lick_threshold: The threshold voltage for detecting a torque contact.
        _volt_per_adc_unit: The conversion factor to translate the raw analog values recorded by the 12-bit ADC into
            voltage in Volts.
    """

    def __init__(
        self,
        lick_threshold: int = 200,
    ) -> None:
        data_codes = {np.uint8(51)}  # kChanged

        # Initializes the subclassed ModuleInterface using the input instance data. Type data is hardcoded.
        super().__init__(
            module_type=np.uint8(4),
            module_id=np.uint8(1),
            mqtt_communication=True,
            data_codes=data_codes,
            mqtt_command_topics=None,
            error_codes=None,
        )

        self._sensor_topic: str = "LickPort/"
        self._lick_threshold: np.uint16 = np.uint16(lick_threshold)

        # Statically computes the voltage resolution of each analog step, assuming a 3.3V ADC with 12-bit resolution.
        self._volt_per_adc_unit = np.round(a=np.float64(3.3 / (2**12)), decimals=8)

    def process_received_data(
        self,
        message: ModuleData | ModuleState,
        mqtt_communication: MQTTCommunication,
        mp_queue: MPQueue,  # type: ignore
    ) -> None:
        # Currently, the only data_code that requires additional processing is code 51 (sensor readout change code).
        if message.event == 51 and message.data_object >= self._lick_threshold:  # Threshold is inclusive
            # If the sensor detects a significantly high voltage, sends an empty message to the sensor MQTT topic,
            # which acts as a binary lick trigger.
            mqtt_communication.send_data(topic=self._sensor_topic, payload=None)

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(
        self,
        lower_threshold: np.uint16 = np.uint16(100),
        upper_threshold: np.uint16 = np.uint16(4095),
        delta_threshold: np.uint16 = np.uint16(50),
        averaging_pool_size: np.uint8 = np.uint8(0),
    ) -> ModuleParameters:
        """Changes the PC-addressable runtime parameters of the LickModule instance.

        Use this method to package and apply new PC-addressable parameters to the LickModule instance managed by this
        Interface class.

        Notes:
            All threshold parameters are inclusive! if you need help determining appropriate threshold levels for
            specific targeted voltages, use get_adc_units_from_volts() method of the interface instance.

        Args:
            lower_threshold: The minimum voltage level, in raw analog units of 12-bit Analog-to-Digital-Converter (ADC),
                that needs to be reported to the PC. Setting this threshold to a number above zero allows high-pass
                filtering the incoming signals. Note, the threshold only applies to the rising edge of the signal,
                going from a high to low value does not respect this threshold.
            upper_threshold: The maximum voltage level, in raw analog units of 12-bit Analog-to-Digital-Converter (ADC),
                that needs to be reported to the PC. Setting this threshold to a number below 4095 allows low-pass
                filtering the incoming signals.
            delta_threshold: The minimum value by which the signal has to change, relative to the previous check, for
                the change to be reported to the PC. Note, if the change is 0, the signal will not be reported to the
                PC, regardless of this parameter value.
            averaging_pool_size: The number of analog pin readouts to average together when checking pin state. This
                is used to smooth the recorded values to avoid communication line noise. It is highly advised to
                have this enabled and set to at least 10 readouts.

        Returns:
            The ModuleParameters message that can be sent to the microcontroller via the send_message() method of
            the MicroControllerInterface class.
        """
        return ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),  # Generally, return code is only helpful for debugging.
            parameter_data=(upper_threshold, lower_threshold, delta_threshold, averaging_pool_size),
        )

    def check_state(self, repetition_delay: np.uint32 = np.uint32(0)) -> OneOffModuleCommand | RepeatedModuleCommand:
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

        Returns:
            The RepeatedModuleCommand or OneOffModuleCommand message that can be sent to the microcontroller via the
            send_message() method of the MicroControllerInterface class.
        """
        if repetition_delay == 0:
            return OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
            )

        return RepeatedModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(1),
            noblock=np.bool(False),
            cycle_delay=repetition_delay,
        )

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


class TorqueInterface(ModuleInterface):
    """Interfaces with TorqueModule instances running on Ataraxis MicroControllers.

    TorqueModule interfaces with a differential torque sensor. The sensor uses differential coding in the millivolt
    range to communicate torque in the CW and the CCW direction. To convert and amplify the output of the torque sensor,
    it is wired to an AD620 microvolt amplifier instrument, that converts the output signal into a single positive
    vector and amplifies its strength to Volts range.

    The TorqueModule further refines the sensor data by ensuring that CCW and CW torque signals behave identically.
    Specifically, it adjusts the signal to scale from 0 to baseline proportionally to the detected torque, regardless
    of torque direction.

    Notes:
        This interface receives torque as a positive uint16_t value from 0 to at most 2046 raw analog units of 3.3v
        12-bit ADC converter. The direction of the torque is reported by the event-code of the received message.

        The default state of the sensor after setup or reset is 0. Until the sensor sends a state message communicating
        a non-zero detected value, it can be safely assumed that the sensor detects the torque of 0. The torque of 0
        essentially has no direction, as it means there is no CW or CCW torque.

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

    Attributes:
        _newton_per_gram_centimeter: Stores the hardcoded conversion factor from gram centimeter to Newton centimeter.
        _capacity_in_newtons_cm: The maximum torque detectable by the sensor in Newtons centimeter.
        _torque_per_adc_unit: The conversion factor to translate raw analog 3.3v 12-bit ADC values to torque in Newtons
            centimeter.
        _force_per_adc_unit: The conversion factor to translate raw analog 3.3v 12-bit ADC values to force in Newtons.
    """

    def __init__(
        self,
        baseline_voltage: int = 2046,
        maximum_voltage: int = 4095,
        sensor_capacity: float = 720.0779,  # 10 oz in
        object_diameter: float = 15.0333,
    ) -> None:
        # data_codes = {np.uint8(51), np.uint8(52)}  # kCCWTorque, kCWTorque

        # Initializes the subclassed ModuleInterface using the input instance data. Type data is hardcoded.
        super().__init__(
            module_type=np.uint8(6),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=None,
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
        self._torque_per_adc_unit = np.round(
            a=(self._capacity_in_newtons_cm / (maximum_voltage - baseline_voltage)),
            decimals=8,
        )

        # Also computes the conversion factor to translate the recorded raw analog readouts of the 3.3V 12-bit ADC to
        # force in Newtons.
        self._force_per_adc_unit = np.round(
            a=self._torque_per_adc_unit / (object_diameter / 2),
            decimals=8,
        )

    def process_received_data(
        self,
        message: ModuleData | ModuleState,
        mqtt_communication: MQTTCommunication,
        mp_queue: MPQueue,  # type: ignore
    ) -> None:
        """Not used."""
        return

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(
        self,
        report_ccw: np.bool = np.bool(True),
        report_cw: np.bool = np.bool(True),
        lower_threshold: np.uint16 = np.uint16(200),
        upper_threshold: np.uint16 = np.uint16(2046),
        delta_threshold: np.uint16 = np.uint16(100),
        averaging_pool_size: np.uint8 = np.uint8(50),
    ) -> ModuleParameters:
        """Changes the PC-addressable runtime parameters of the TorqueModule instance.

        Use this method to package and apply new PC-addressable parameters to the TorqueModule instance managed by this
        Interface class.

        Notes:
            All threshold parameters are inclusive! If you need help determining appropriate threshold levels for
            specific targeted torque levels, use get_adc_units_from_torque() method of the interface instance.

        Args:
            report_ccw: Determines whether the sensor should report torque in the CounterClockwise (CCW) direction.
            report_cw: Determines whether the sensor should report torque in the Clockwise (CW) direction.
            lower_threshold: The minimum torque level, in raw analog units of 12-bit Analog-to-Digital-Converter (ADC),
                that needs to be reported to the PC. Setting this threshold to a number above zero allows high-pass
                filtering the incoming signals.
            upper_threshold: The maximum torque level, in raw analog units of 12-bit Analog-to-Digital-Converter (ADC),
                that needs to be reported to the PC. Setting this threshold to a number below 4095 allows low-pass
                filtering the incoming signals.
            delta_threshold: The minimum value by which the signal has to change, relative to the previous check, for
                the change to be reported to the PC. Note, if the change is 0, the signal will not be reported to the
                PC, regardless of this parameter value.
            averaging_pool_size: The number of analog pin readouts to average together when checking pin state. This
                is used to smooth the recorded values to avoid communication line noise. It is highly advised to
                have this enabled and set to at least 10 readouts.

        Returns:
            The ModuleParameters message that can be sent to the microcontroller via the send_message() method of
            the MicroControllerInterface class.
        """
        return ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),  # Generally, return code is only helpful for debugging.
            parameter_data=(
                report_ccw,
                report_cw,
                upper_threshold,
                lower_threshold,
                delta_threshold,
                averaging_pool_size,
            ),
        )

    def check_state(self, repetition_delay: np.uint32 = np.uint32(0)) -> OneOffModuleCommand | RepeatedModuleCommand:
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

        Returns:
            The RepeatedModuleCommand or OneOffModuleCommand message that can be sent to the microcontroller via the
            send_message() method of the MicroControllerInterface class.
        """
        if repetition_delay == 0:
            return OneOffModuleCommand(
                module_type=self._module_type,
                module_id=self._module_id,
                return_code=np.uint8(0),
                command=np.uint8(1),
                noblock=np.bool(False),
            )

        return RepeatedModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(1),
            noblock=np.bool(False),
            cycle_delay=repetition_delay,
        )

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
        Since the current VR setup uses 3 screens, the current implementation of ScreenModule is designed to interface
        with all 3 screens at the same time. In the future, the module may be refactored to allow addressing individual
        screens.

        The physical wiring of the module also allows manual screen manipulation via the buttons on the control panel
        if the ScreenModule is not actively delivering a toggle pulse. However, changing the state of the screen
        manually is strongly discouraged, as it interferes with tracking the state of the screen via software.
    """

    def __init__(self) -> None:
        error_codes = {np.uint8(51)}  # kOutputLocked

        # kOn, kOff
        # data_codes = {np.uint8(52), np.uint8(53)}

        super().__init__(
            module_type=np.uint8(7),
            module_id=np.uint8(1),
            mqtt_communication=False,
            data_codes=None,  # None of the data codes needs additional processing, so statically set to None
            mqtt_command_topics=None,
            error_codes=error_codes,
        )

    def process_received_data(
        self,
        message: ModuleData | ModuleState,
        mqtt_communication: MQTTCommunication,
        mp_queue: MPQueue,  # type: ignore
    ) -> None:
        """Not used."""
        return

    def parse_mqtt_command(self, topic: str, payload: bytes | bytearray) -> None:
        """Not used."""
        return

    def set_parameters(self, pulse_duration: np.uint32 = np.uint32(1000000)) -> ModuleParameters:
        """Changes the PC-addressable runtime parameters of the ScreenModule instance.

        Use this method to package and apply new PC-addressable parameters to the ScreenModule instance managed by
        this Interface class.

        Args:
            pulse_duration: The duration, in microseconds, of each emitted screen toggle pulse HIGH phase. This is
                equivalent to the duration of the control panel POWER button press. The main criterion for this
                parameter is to be long enough for the converter board to register the press.

        Returns:
            The ModuleParameters message that can be sent to the microcontroller via the send_message() method of
            the MicroControllerInterface class.
        """
        return ModuleParameters(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            parameter_data=(pulse_duration,),
        )

    def toggle(self) -> OneOffModuleCommand:
        """Triggers the ScreenModule to briefly simulate pressing the POWER button of the scree control board.

        This command is used to turn the connected display on or off. The new state of the display depends on the
        current state of the display when the command is issued. Since the displays can also be controller manually
        (via the physical control board buttons), the state of the display can also be changed outside this interface,
        although it is highly advised to NOT change screen states manually.

        Notes:
            It is highly recommended to use this command to manipulate display sates, as it ensures that display state
            changes are logged for further data analysis.

        Returns:
            The OneOffModuleCommand message that can be sent to the microcontroller via the send_message() method of the
            MicroControllerInterface class.
        """
        return OneOffModuleCommand(
            module_type=self._module_type,
            module_id=self._module_id,
            return_code=np.uint8(0),
            command=np.uint8(1),
            noblock=np.bool(False),
        )
