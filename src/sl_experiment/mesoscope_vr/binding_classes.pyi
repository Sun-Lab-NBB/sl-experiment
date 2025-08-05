from pathlib import Path

import numpy as np
from _typeshed import Incomplete
from sl_shared_assets import ZaberPositions
from ataraxis_video_system import VideoSystem
from ataraxis_data_structures import DataLogger
from ataraxis_communication_interface import MicroControllerInterface

from .tools import get_system_configuration as get_system_configuration
from .zaber_bindings import (
    ZaberAxis as ZaberAxis,
    ZaberConnection as ZaberConnection,
)
from ..shared_components import (
    TTLInterface as TTLInterface,
    LickInterface as LickInterface,
    BreakInterface as BreakInterface,
    ValveInterface as ValveInterface,
    ScreenInterface as ScreenInterface,
    TorqueInterface as TorqueInterface,
    EncoderInterface as EncoderInterface,
)

class ZaberMotors:
    """Interfaces with Zaber motors that control the position of the HeadBar, LickPort, and the running Wheel inside the
    mesoscope cage.

    This class abstracts working with Zaber motors that move the HeadBar in Z, Pitch, and Roll axes, the LickPort in
    X, Y, and Z axes, and the Wheel in X axis. It is used by the major runtime classes, such as _MesoscopeExperiment,
    to position various Mesoscope-VR components and the mouse in a way that promotes data acquisition and task
    performance.

    Notes:
        The class is designed to transition the motors between a set of predefined states and should not be used
        directly by the user. It does not contain the guards that notify users about risks associated with moving the
        motors. Do not use any methods from this class unless you know what you are doing. It is possible to damage
        the motors, the mesoscope, or harm the animal.

        To fine-tune the position of any Zaber motors in real time, use the main Zaber Launcher interface
        (https://software.zaber.com/zaber-launcher/download) installed on the VRPC.

        Unless you know that the motors are homed and not parked, always call the prepare_motors() method before
        calling any other methods. Otherwise, Zaber controllers will likely ignore the issued commands.

    Args:
        zaber_positions_path: The path to the zaber_positions.yaml file that stores the motor positions saved during the
            previous runtime.

    Attributes:
        _headbar: Stores the Connection class instance that manages the USB connection to a daisy-chain of Zaber
            devices (controllers) that allow repositioning the headbar holder.
        _headbar_z: The ZaberAxis class instance for the headbar z-axis motor.
        _headbar_pitch: The ZaberAxis class instance for the headbar pitch-axis motor.
        _headbar_roll: The ZaberAxis class instance for the headbar roll-axis motor.
        _wheel: Stores the Connection class instance that manages the USB connection to a daisy-chain of Zaber
            devices (controllers) that allow repositioning the running wheel.
        _wheel_x: The ZaberAxis class instance for the running-wheel X-axis motor.
        _lickport: Stores the Connection class instance that manages the USB connection to a daisy-chain of Zaber
            devices (controllers) that allow repositioning the lickport.
        _lickport_z: Stores the Axis (motor) class that controls the position of the lickport along the Z axis.
        _lickport_x: Stores the Axis (motor) class that controls the position of the lickport along the X axis.
        _lickport_y: Stores the Axis (motor) class that controls the position of the lickport along the Y axis.
        _previous_positions: An instance of _ZaberPositions class that stores the positions of Zaber motors during a
           previous runtime. If this data is not available, this attribute is set to None to indicate there are no
           previous positions to use.
    """

    _headbar: ZaberConnection
    _wheel: ZaberConnection
    _lickport: ZaberConnection
    _headbar_z: ZaberAxis
    _headbar_pitch: ZaberAxis
    _headbar_roll: ZaberAxis
    _lickport_z: ZaberAxis
    _lickport_y: ZaberAxis
    _lickport_x: ZaberAxis
    _wheel_x: ZaberAxis
    _previous_positions: None | ZaberPositions
    def __init__(self, zaber_positions_path: Path) -> None: ...
    def restore_position(self) -> None:
        """Restores the Zaber motor positions to the states recorded at the end of the previous runtime.

        For most runtimes, this method is used to restore the motors to the state used during a previous experiment or
        training session for each animal. Since all animals are slightly different, the optimal Zaber motor positions
        will vary slightly for each animal.

        Notes:
            If previous positions are not available, the method falls back to moving the motors to the general
            'mounting' positions saved in the non-volatile memory of each motor controller. These positions are designed
            to work for most animals and provide an initial position for the animal to be mounted into the VR rig.

            This method moves all Zaber axes in parallel to optimize runtime speed. This relies on the Mesoscope-VR
            system to be assembled in a way where it is safe to move all motors at the same time.
        """
    def prepare_motors(self) -> None:
        """Unparks and homes all motors.

        This method should be used at the beginning of each runtime (experiment, training, etc.) to ensure all Zaber
        motors can be moved (are not parked) and have a stable point of reference. The motors are left at their
        respective homing positions at the end of this method's runtime, and it is assumed that a different class
        method is called after this method to set the motors into the desired position.

        Notes:
            This method moves all motor axes in parallel to optimize runtime speed.
        """
    def park_position(self) -> None:
        """Moves all motors to their parking positions and parks (locks) them preventing future movements.

        This method should be used at the end of each runtime (experiment, training, etc.) to ensure all Zaber motors
        are positioned in a way that guarantees that they can be homed during the next runtime.

        Notes:
            The motors are moved to the parking positions stored in the non-volatile memory of each motor controller.
            This method moves all motor axes in parallel to optimize runtime speed.
        """
    def maintenance_position(self) -> None:
        """Moves all motors to the Mesoscope-VR system maintenance position.

        This position is stored in the non-volatile memory of each motor controller. Primarily, this position is used
        during the water valve calibration and during running-wheel maintenance (cleaning, replacing surface material,
        etc.).

        Notes:
            This method moves all motor axes in parallel to optimize runtime speed.

            Formerly, the only maintenance step was the calibration of the water-valve, so some low-level functions
            still reference it as 'valve-position' and 'calibrate-position'.
        """
    def mount_position(self) -> None:
        """Moves all motors to the animal mounting position.

        This position is stored in the non-volatile memory of each motor controller. This position is used when the
        animal is mounted into the VR rig to provide the experimenter with easy access to the head bar holder.

        Notes:
            This method moves all MOTOR axes in parallel to optimize runtime speed.
        """
    def unmount_position(self) -> None:
        """Moves the lick-port back to the mount position in all axes while keeping all other motors in their current
        positions.

        This command facilitates removing (unmounting) the animal from the VR rig while being safe to execute when the
        mesoscope objective and other mesoscope-VR elements are positioned for imaging.

        Notes:
            Technically, calling the mount_position() method after generating a new ZaberMotors snapshot will behave
            identically to this command. However, to improve runtime safety and the clarity of the class API, it is
            highly encouraged to use this method to unmount the animal.
        """
    def generate_position_snapshot(self) -> ZaberPositions:
        """Queries the current positions of all managed Zaber motors, packages the position data into a ZaberPositions
        instance, and returns it to the caller.

        This method is used by runtime classes to update the ZaberPositions instance cached on disk for each animal.
        The method also updates the local ZaberPositions copy stored inside the class instance with the data from the
        generated snapshot. Primarily, this has to be done to support the Zaber motor shutdown sequence.
        """
    def wait_until_idle(self) -> None:
        """Blocks in-place while at least one motor in the managed motor group(s) is moving.

        Primarily, this method is used to issue commands to multiple motor groups and then block until all motors in
        all groups finish moving. This optimizes the overall time taken to move the motors.
        """
    def disconnect(self) -> None:
        """Disconnects from the communication port(s) of the managed motor groups.

        This method should be called after the motors are parked (moved to their final parking position) to release
        the connection resources. If this method is not called, the runtime will NOT be able to terminate.
        """
    def park_motors(self) -> None:
        """Parks all managed motor groups, preventing them from being moved via this library or Zaber GUI until
        they are unparked via the unpark_motors() command."""
    def unpark_motors(self) -> None:
        """Unparks all managed motor groups, allowing them to be moved via this library or the Zaber GUI."""
    @property
    def is_connected(self) -> bool:
        """Returns True if all managed motor connections are active and False if at least one connection is inactive."""

class MicroControllerInterfaces:
    """Interfaces with all Ataraxis Micro Controller (AMC) devices that control Mesoscope-VR system hardware and acquire
    non-video behavior data.

    This class interfaces with the three AMC controllers used during various runtimes: Actor, Sensor, and Encoder. The
    class exposes methods to send commands to the hardware modules managed by these microcontrollers. In turn, these
    modules control specific components of the Mesoscope-Vr system, such as rotary encoders, solenoid valves, and
    conductive lick sensors.

    Notes:
        This class is primarily intended to be used internally by the _MesoscopeExperiment and _BehaviorTraining
        classes. Our maintenance CLI (sl-maintain) is the only exception to this rule, as it directly uses this class to
        facilitate Mesoscope-VR maintenance tasks.

        Calling the initializer does not start the underlying processes. Use the start() method before issuing other
        commands to properly initialize all remote processes. This design is intentional and is used during experiment
        and training runtimes to parallelize data preprocessing for the previous session and runtime preparation for the
        following session.

    Args:
        data_logger: The initialized DataLogger instance used to log the data generated by the managed microcontrollers.
            For most runtimes, this argument is resolved by the _MesoscopeExperiment or _BehaviorTraining classes that
            initialize this class.

    Attributes:
        _started: Tracks whether the VR system and experiment runtime are currently running.
        _system_configuration: Stores the configuration parameters used by the Mesoscope-VR system.
        _sensor_polling_delay: Stores the delay, in microseconds, between any two consecutive sensor readout polls. This
            delay is the same for most sensor modules.
        _previous_volume: Tracks the volume of water dispensed during previous deliver_reward() calls.
        _previous_tone_duration: Tracks the auditory tone duration during previous deliver_reward() or simulate_reward()
            calls.
        _screen_state: Tracks the current VR screen state.
        _frame_monitoring: Tracks the current mesoscope frame monitoring state.
        _torque_monitoring: Tracks the current torque monitoring state.
        _lick_monitoring: Tracks the current lick monitoring state.
        _encoder_monitoring: Tracks the current encoder monitoring state.
        _break_state: Tracks the current break state.
        _delay_timer: Stores a millisecond-precise timer used by certain sequential command methods.
        wheel_break: The interface that controls the electromagnetic break attached to the running wheel.
        valve: The interface that controls the solenoid water valve that delivers water to the animal.
        screens: The interface that controls the power state of the VR display screens.
        _actor: The main interface for the 'Actor' Ataraxis Micro Controller (AMC) device.
        mesoscope_frame: The interface that monitors frame acquisition timestamp signals sent by the mesoscope.
        lick: The interface that monitors animal's interactions with the lick sensor (detects licks).
        torque: The interface that monitors the torque applied by the animal to the running wheel.
        _sensor: The main interface for the 'Sensor' Ataraxis Micro Controller (AMC) device.
        wheel_encoder: The interface that monitors the rotation of the running wheel and converts it into the distance
            traveled by the animal.
        _encoder: The main interface for the 'Encoder' Ataraxis Micro Controller (AMC) device.
    """

    _started: bool
    _system_configuration: Incomplete
    _sensor_polling_delay: float
    _previous_volume: float
    _previous_tone_duration: int
    _screen_state: bool
    _frame_monitoring: bool
    _torque_monitoring: bool
    _lick_monitoring: bool
    _encoder_monitoring: bool
    _break_state: bool
    _delay_timer: Incomplete
    wheel_break: Incomplete
    valve: Incomplete
    screens: Incomplete
    _actor: MicroControllerInterface
    mesoscope_frame: TTLInterface
    lick: LickInterface
    torque: TorqueInterface
    _sensor: MicroControllerInterface
    wheel_encoder: EncoderInterface
    _encoder: MicroControllerInterface
    def __init__(self, data_logger: DataLogger) -> None: ...
    def __del__(self) -> None:
        """Ensures that all hardware resources are released when the object is garbage-collected."""
    def start(self) -> None:
        """Starts MicroController communication processes and configures all hardware modules to use the runtime
        parameters loaded from the acquisition system configuration file.

        This method sets up the necessary assets that enable MicroController-PC communication. Until this method is
        called, all other class methods will not function correctly.

        Notes:
            After calling this method, most hardware modules will be initialized to an idle state. The only exception to
            this rule is the wheel break, which initializes to the 'engaged' state. Use other class methods to
            switch individual hardware modules into the desired state.

            Since most modules initialize to an idle state, they will not be generating data. Therefore, it is safe
            to call this method before enabling the DataLogger class. However, it is strongly advised to enable the
            DataLogger as soon as possible to avoid data piling up in the buffer.
        """
    def stop(self) -> None:
        """Stops all MicroController communication processes and releases all resources.

        This method needs to be called at the end of each runtime to release the resources reserved by the start()
        method. Until the stop() method is called, the DataLogger instance may receive data from running
        MicroControllers, so calling this method also guarantees no MicroController data will be lost if the DataLogger
        process is terminated.
        """
    def enable_encoder_monitoring(self) -> None:
        """Enables wheel encoder monitoring at a 2 kHz rate.

        This means that, at most, the Encoder will send the data to the PC at the 2 kHz rate. The Encoder collects data
        at the native rate supported by the microcontroller hardware, which likely exceeds the reporting rate.
        """
    def disable_encoder_monitoring(self) -> None:
        """Stops monitoring the wheel encoder."""
    def enable_break(self) -> None:
        """Engages the wheel break at maximum strength, preventing the animal from running on the wheel."""
    def disable_break(self) -> None:
        """Disengages the wheel break, enabling the animal to run on the wheel."""
    def enable_vr_screens(self) -> None:
        """Sets the VR screens to be ON."""
    def disable_vr_screens(self) -> None:
        """Sets the VR screens to be OFF."""
    def enable_mesoscope_frame_monitoring(self) -> None:
        """Enables monitoring the TTL pulses sent by the mesoscope to communicate when it is scanning a frame at
        ~ 1 kHZ rate.

        The mesoscope sends the HIGH phase of the TTL pulse while it is scanning the frame, which produces a pulse of
        ~100ms. This is followed by ~5ms LOW phase during which the Galvos are executing the flyback procedure. This
        command checks the state of the TTL pin at the 1 kHZ rate, which is enough to accurately report both phases.
        """
    def disable_mesoscope_frame_monitoring(self) -> None:
        """Stops monitoring the TTL pulses sent by the mesoscope to communicate when it is scanning a frame."""
    def enable_lick_monitoring(self) -> None:
        """Enables monitoring the state of the conductive lick sensor at ~ 1 kHZ rate.

        The lick sensor measures the voltage across the lick sensor and reports surges in voltage to the PC as a
        reliable proxy for tongue-to-sensor contact. Most lick events span at least 100 ms of time and, therefore, the
        rate of 1 kHZ is adequate for resolving all expected single-lick events.
        """
    def disable_lick_monitoring(self) -> None:
        """Stops monitoring the conductive lick sensor."""
    def enable_torque_monitoring(self) -> None:
        """Enables monitoring the torque sensor at ~ 1 kHZ rate.

        The torque sensor detects CW and CCW torques applied by the animal to the wheel. Currently, we do not have a
        way of reliably calibrating the sensor, so detected torque magnitudes are only approximate. However, the sensor
        reliably distinguishes large torques from small torques and accurately tracks animal motion activity when the
        wheel break is engaged.
        """
    def disable_torque_monitoring(self) -> None:
        """Stops monitoring the torque sensor."""
    def open_valve(self) -> None:
        """Opens the water reward solenoid valve.

        This method is primarily used to prime the water line with water before the first experiment or training session
        of the day.
        """
    def close_valve(self) -> None:
        """Closes the water reward solenoid valve."""
    def deliver_reward(self, volume: float = 5.0, tone_duration: int = 300, ignore_parameters: bool = False) -> None:
        """Pulses the water reward solenoid valve for the duration of time necessary to deliver the provided volume of
        water.

        This method assumes that the valve has been calibrated before calling this method. It uses the calibration data
        provided at class instantiation to determine the period of time the valve should be kept open to deliver the
        requested volume of water.

        Args:
            volume: The volume of water to deliver, in microliters.
            tone_duration: The duration of the auditory tone, in milliseconds, to emit while delivering the water
                reward.
            ignore_parameters: Determines whether to ignore the volume and tone_duration arguments. Calling the method
                with this argument ensures that the delivered reward always uses the same volume and tone_duration as
                the previous reward command. Primarily, this argument is used when receiving reward commands from Unity.
        """
    def simulate_reward(self, tone_duration: int = 300) -> None:
        """Simulates delivering water reward by emitting an audible 'reward' tone without triggering the valve.

        This method is used during training when the animal refuses to consume water rewards. In this case, the water
        rewards are not delivered, but the tones are still played to notify the animal it is performing the task as
        required.

        Args:
            tone_duration: The duration of the auditory tone, in milliseconds, to emit while simulating the water
                reward delivery.
        """
    def configure_reward_parameters(self, volume: float = 5.0, tone_duration: int = 300) -> None:
        """Configures all future water rewards to use the provided volume and tone duration parameters.

        Primarily, this function is used to reconfigure the system from GUI and trigger reward delivery from Unity.

        Args:
            volume: The volume of water to deliver, in microliters.
            tone_duration: The duration of the auditory tone, in milliseconds, to emit while delivering the water
                reward.
        """
    def reference_valve(self) -> None:
        """Runs the reference valve calibration procedure.

        Reference calibration is functionally similar to the calibrate_valve() method runtime. It is, however, optimized
        to deliver the overall volume of water recognizable for the human eye looking at the syringe holding the water
        (water 'tank' used in our system). Additionally, this uses the 5 uL volume as the reference volume, which
        matches the volume we use during experiments and training sessions.

        The reference calibration HAS to be run with the water line being primed, deaerated, and the holding ('tank')
        syringe filled exactly to the 5 mL mark. This procedure is designed to dispense 5 uL of water 200 times, which
        should overall dispense ~ 1 ml of water.
        """
    def calibrate_valve(self, pulse_duration: int = 15) -> None:
        """Cycles solenoid valve opening and closing 500 times to determine the amount of water dispensed by the input
        pulse_duration.

        The valve is kept open for the specified number of milliseconds. Between pulses, the valve is kept closed for
        300 ms. Due to our valve design, keeping the valve closed for less than 200-300 ms generates a large pressure
        at the third (Normally Open) port, which puts unnecessary strain on the port plug and internal mechanism of the
        valve.

        Notes:
            The calibration should be run with the following durations: 15 ms, 30 ms, 45 ms, and 60 ms. During testing,
            we found that these values cover the water reward range from 2 uL to 10 uL, which is enough to cover most
            training and experiment runtimes.

            Make sure that the water line is primed, deaerated, and the holding ('tank') syringe filled exactly to the
            5 mL mark at the beginning of each calibration cycle. Depending on the calibrated pulse_duration, you may
            need to refill the syringe during the calibration runtime.

        Args:
            pulse_duration: The duration, in milliseconds, the valve is kept open at each calibration cycle
        """
    def reset_mesoscope_frame_count(self) -> None:
        """Resets the mesoscope frame counter to 0."""
    def reset_distance_tracker(self) -> None:
        """Resets the total distance traveled by the animal since runtime onset and the current position of the animal
        relative to runtime onset to 0.
        """
    @property
    def mesoscope_frame_count(self) -> np.uint64:
        """Returns the total number of mesoscope frame acquisition pulses recorded since runtime onset."""
    @property
    def delivered_water_volume(self) -> np.float64:
        """Returns the total volume of water, in microliters, dispensed by the valve since runtime onset."""
    @property
    def lick_count(self) -> np.uint64:
        """Returns the total number of licks recorded since runtime onset."""
    @property
    def traveled_distance(self) -> np.float64:
        """Returns the total distance, in centimeters, traveled by the animal since runtime onset.

        This value does not account for the direction of travel and is a monotonically increasing count of traveled
        centimeters.
        """
    @property
    def position(self) -> np.float64:
        """Returns the current absolute position of the animal, in Unity units, relative to runtime onset."""

class VideoSystems:
    """Interfaces with all cameras managed by Ataraxis Video System (AVS) classes that acquire and save camera frames
    as .mp4 video files.

    This class interfaces with the three AVS cameras used during various runtimes to record animal behavior: the face
    camera and the two body cameras (the left camera and the right camera). The face camera is a high-grade scientific
    camera that records the animal's face and pupil. The left and right cameras are lower-end security cameras recording
    the animal's body from the left and right sides.

    Notes:
        This class is primarily intended to be used internally by the _MesoscopeExperiment and _BehaviorTraining
        classes. Do not initialize this class directly unless you know what you are doing.

        Calling the initializer does not start the underlying processes. Call the appropriate start() method to start
        acquiring and displaying face and body camera frames (there is a separate method for these two groups). Call
        the appropriate save() method to start saving the acquired frames to video files. Note that there is a single
        'global' stop() method that works for all cameras at the same time.

        The class is designed to be 'lock-in'. Once a camera is enabled, the only way to disable frame acquisition is to
        call the main stop() method. Similarly, once frame saving is started, there is no way to disable it without
        stopping the whole class. This is an intentional design decision optimized to the specific class use-pattern in
        our lab.

    Args:
        data_logger: The initialized DataLogger instance used to log the data generated by the managed cameras. For most
            runtimes, this argument is resolved by the _MesoscopeExperiment or _BehaviorTraining classes that
            initialize this class.
        output_directory: The path to the directory where to output the generated .mp4 video files. Each managed camera
            generates a separate video file saved in the provided directory. For most runtimes, this argument is
            resolved by the _MesoscopeExperiment or _BehaviorTraining classes that initialize this class.

    Attributes:
        _face_camera_started: Tracks whether the face camera frame acquisition is running.
        _body_cameras_started: Tracks whether the body cameras frame acquisition is running.
        _system_configuration: Stores the configuration parameters used by the Mesoscope-VR system.
        _face-camera: The interface that captures and saves the frames acquired by the 9MP scientific camera aimed at
            the animal's face and eye from the left side (via a hot mirror).
        _left_camera: The interface that captures and saves the frames acquired by the 1080P security camera aimed on
            the left side of the animal and the right and center VR screens.
        _right_camera: The interface that captures and saves the frames acquired by the 1080P security camera aimed on
            the right side of the animal and the left VR screen.
    """

    _face_camera_started: bool
    _body_cameras_started: bool
    _system_configuration: Incomplete
    _face_camera: VideoSystem
    _left_camera: VideoSystem
    _right_camera: VideoSystem
    def __init__(self, data_logger: DataLogger, output_directory: Path) -> None: ...
    def __del__(self) -> None:
        """Ensures all hardware resources are released when the class is garbage-collected."""
    def start_face_camera(self) -> None:
        """Starts face camera frame acquisition.

        This method sets up both the frame acquisition (producer) process and the frame saver (consumer) process.
        However, the consumer process will not save any frames until the save_face_camera_frames () method is called.
        """
    def start_body_cameras(self) -> None:
        """Starts left and right (body) camera frame acquisition.

        This method sets up both the frame acquisition (producer) process and the frame saver (consumer) process for
        both cameras. However, the consumer processes will not save any frames until the save_body_camera_frames ()
        method is called.
        """
    def save_face_camera_frames(self) -> None:
        """Starts saving the frames acquired by the face camera as a video file."""
    def save_body_camera_frames(self) -> None:
        """Starts saving the frames acquired by the left and right body cameras as a video file."""
    def stop(self) -> None:
        """Stops saving all camera frames and terminates the managed VideoSystems.

        This method needs to be called at the end of each runtime to release the resources reserved by the start()
        methods. Until the stop() method is called, the DataLogger instance may receive data from running
        VideoSystems, so calling this method also guarantees no VideoSystem data will be lost if the DataLogger
        process is terminated. Similarly, this guarantees the integrity of the generated video files.
        """
    @property
    def face_camera_log_path(self) -> Path:
        """Returns the path to the compressed .npz archive that stores the data logged by the face camera during
        runtime."""
    @property
    def left_camera_log_path(self) -> Path:
        """Returns the path to the compressed .npz archive that stores the data logged by the left body camera during
        runtime."""
    @property
    def right_camera_log_path(self) -> Path:
        """Returns the path to the compressed .npz archive that stores the data logged by the right body camera during
        runtime."""
