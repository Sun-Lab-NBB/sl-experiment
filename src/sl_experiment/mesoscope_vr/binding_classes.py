"""This module binds low-level API classes for all Mesoscope-VR components (cameras, microcontrollers, Zaber motors).
These bindings streamline the API used to interface with these components during experiment and training runtimes.
"""

from pathlib import Path

import numpy as np
from sl_shared_assets import ZaberPositions, MesoscopeMicroControllers
from ataraxis_video_system import (
    VideoCodecs,
    VideoSystem,
    VideoFormats,
    CameraBackends,
    GPUEncoderPresets,
    InputPixelFormats,
    OutputPixelFormats,
)
from ataraxis_base_utilities import LogLevel, console
from ataraxis_data_structures import DataLogger
from ataraxis_time.time_helpers import TimeUnits, convert_time
from ataraxis_communication_interface import MicroControllerInterface

from .tools import get_system_configuration
from .zaber_bindings import ZaberAxis, ZaberConnection
from ..shared_components import (
    TTLInterface,
    LickInterface,
    BrakeInterface,
    ValveInterface,
    ScreenInterface,
    TorqueInterface,
    EncoderInterface,
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

    def __init__(self, zaber_positions_path: Path) -> None:
        # Retrieves the Mesoscope-VR system configuration parameters.
        system_configuration = get_system_configuration()

        # Initializes the connection classes first to ensure all classes exist in case the runtime encounters
        # an error during connection.
        self._headbar: ZaberConnection = ZaberConnection(port=system_configuration.assets.headbar_port)
        self._wheel: ZaberConnection = ZaberConnection(port=system_configuration.assets.wheel_port)
        self._lickport: ZaberConnection = ZaberConnection(port=system_configuration.assets.lickport_port)

        # HeadBar controller (zaber). This is an assembly of 3 zaber controllers (devices) that allow moving the
        # headbar attached to the mouse's head in Z, Roll, and Pitch axes. Note, this assumes that the chaining
        # order of individual zaber devices is fixed and is always Z-Pitch-Roll.
        self._headbar.connect()
        self._headbar_z: ZaberAxis = self._headbar.get_device(index=0).axis
        self._headbar_pitch: ZaberAxis = self._headbar.get_device(index=1).axis
        self._headbar_roll: ZaberAxis = self._headbar.get_device(index=2).axis

        # Lickport controller (zaber). This is an assembly of 3 zaber controllers (devices) that allow moving the
        # lick tube in Z, X, and Y axes. Note, this assumes that the chaining order of individual zaber devices is
        # fixed and is always Z-X-Y.
        self._lickport.connect()
        self._lickport_z: ZaberAxis = self._lickport.get_device(index=0).axis
        self._lickport_y: ZaberAxis = self._lickport.get_device(index=1).axis
        self._lickport_x: ZaberAxis = self._lickport.get_device(index=2).axis

        # Wheel controller (zaber). Currently, this assembly includes a single controller (device) that allows moving
        # the running wheel in the X axis.
        self._wheel.connect()
        self._wheel_x: ZaberAxis = self._wheel.get_device(index=0).axis

        # If the previous positions path points to an existing .yaml file, loads the data from the file into
        # _ZaberPositions instance. Otherwise, sets the previous_positions attribute to None to indicate there are no
        # previous positions.
        self._previous_positions: None | ZaberPositions = None
        if zaber_positions_path.exists():
            self._previous_positions = ZaberPositions.from_yaml(zaber_positions_path)
        else:
            message = (
                "No previous position data found when attempting to load Zaber motor positions used during a previous "
                "runtime. Setting all Zaber motors to use the default positions cached in non-volatile memory of each "
                "motor controller."
            )
            console.echo(message=message, level=LogLevel.ERROR)

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
        # Disables the safety motor lock before moving the motors.
        self.unpark_motors()

        # If previous position data is available, restores all motors to the positions used during previous sessions.
        # Otherwise, sets HeadBar and Wheel to mounting position and the LickPort to parking position. For LickPort,
        # the only difference between parking and mounting positions is that the mounting position is retracted further
        # away from the animal than the parking position.
        self._headbar_z.move(
            position=self._headbar_z.mount_position
            if self._previous_positions is None
            else self._previous_positions.headbar_z,
        )
        self._headbar_pitch.move(
            position=self._headbar_pitch.mount_position
            if self._previous_positions is None
            else self._previous_positions.headbar_pitch,
        )
        self._headbar_roll.move(
            position=self._headbar_roll.mount_position
            if self._previous_positions is None
            else self._previous_positions.headbar_roll,
        )
        self._wheel_x.move(
            position=self._wheel_x.mount_position
            if self._previous_positions is None
            else self._previous_positions.wheel_x,
        )
        self._lickport_z.move(
            position=self._lickport_z.park_position
            if self._previous_positions is None
            else self._previous_positions.lickport_z,
        )
        self._lickport_x.move(
            position=self._lickport_x.park_position
            if self._previous_positions is None
            else self._previous_positions.lickport_x,
        )
        self._lickport_y.move(
            position=self._lickport_y.park_position
            if self._previous_positions is None
            else self._previous_positions.lickport_y,
        )

        # Waits for all motors to finish moving before returning to caller.
        self.wait_until_idle()

        # Prevents further interaction with the motors without manually disabling the parking lock.
        self.park_motors()

    def prepare_motors(self) -> None:
        """Unparks and homes all motors.

        This method should be used at the beginning of each runtime (experiment, training, etc.) to ensure all Zaber
        motors can be moved (are not parked) and have a stable point of reference. The motors are left at their
        respective homing positions at the end of this method's runtime, and it is assumed that a different class
        method is called after this method to set the motors into the desired position.

        Notes:
            This method moves all motor axes in parallel to optimize runtime speed.
        """
        # Disables the safety motor lock before moving the motors.
        self.unpark_motors()

        # Homes all motors in-parallel.
        self._headbar_z.home()
        self._headbar_pitch.home()
        self._headbar_roll.home()
        self._wheel_x.home()
        self._lickport_z.home()
        self._lickport_x.home()
        self._lickport_y.home()

        # Waits for all motors to finish moving before returning to caller.
        self.wait_until_idle()

        # Prevents further interaction with the motors without manually disabling the parking lock.
        self.park_motors()

    def park_position(self) -> None:
        """Moves all motors to their parking positions and parks (locks) them preventing future movements.

        This method should be used at the end of each runtime (experiment, training, etc.) to ensure all Zaber motors
        are positioned in a way that guarantees that they can be homed during the next runtime.

        Notes:
            The motors are moved to the parking positions stored in the non-volatile memory of each motor controller.
            This method moves all motor axes in parallel to optimize runtime speed.
        """
        # Disables the safety motor lock before moving the motors.
        self.unpark_motors()

        # Moves all Zaber motors to their parking positions
        self._headbar_z.move(position=self._headbar_z.park_position)
        self._headbar_pitch.move(position=self._headbar_pitch.park_position)
        self._headbar_roll.move(position=self._headbar_roll.park_position)
        self._wheel_x.move(position=self._wheel_x.park_position)
        self._lickport_z.move(position=self._lickport_z.park_position)
        self._lickport_x.move(position=self._lickport_x.park_position)
        self._lickport_y.move(position=self._lickport_y.park_position)

        # Waits for all motors to finish moving before returning to caller.
        self.wait_until_idle()

        # Prevents further interaction with the motors without manually disabling the parking lock.
        self.park_motors()

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
        # Disables the safety motor lock before moving the motors.
        self.unpark_motors()

        # Moves all motors to their maintenance positions
        self._headbar_z.move(position=self._headbar_z.maintenance_position)
        self._headbar_pitch.move(position=self._headbar_pitch.maintenance_position)
        self._headbar_roll.move(position=self._headbar_roll.maintenance_position)
        self._wheel_x.move(position=self._wheel_x.maintenance_position)
        self._lickport_z.move(position=self._lickport_z.maintenance_position)
        self._lickport_x.move(position=self._lickport_x.maintenance_position)
        self._lickport_y.move(position=self._lickport_y.maintenance_position)

        # Waits for all motors to finish moving before returning to caller.
        self.wait_until_idle()

        # Prevents further interaction with the motors without manually disabling the parking lock.
        self.park_motors()

    def mount_position(self) -> None:
        """Moves all motors to the animal mounting position.

        This position is stored in the non-volatile memory of each motor controller. This position is used when the
        animal is mounted into the VR rig to provide the experimenter with easy access to the head bar holder.

        Notes:
            This method moves all MOTOR axes in parallel to optimize runtime speed.
        """
        # Disables the safety motor lock before moving the motors.
        self.unpark_motors()

        # Moves all lickport motors to the mount position
        self._lickport_z.move(position=self._lickport_z.mount_position)
        self._lickport_x.move(position=self._lickport_x.mount_position)
        self._lickport_y.move(position=self._lickport_y.mount_position)

        # If previous positions are not available, moves the rest of the motors to the default mounting positions
        if self._previous_positions is None:
            self._headbar_z.move(position=self._headbar_z.mount_position)
            self._headbar_pitch.move(position=self._headbar_pitch.mount_position)
            self._headbar_roll.move(position=self._headbar_roll.mount_position)
            self._wheel_x.move(position=self._wheel_x.mount_position)

        # If previous positions are available, restores other motors to the position used during the previous runtime.
        # This relies on the idea that mounting is primarily facilitated by moving the lickport away, while all mouse
        # positioning motors can be set to the parameters optimal for the mouse being mounted.
        else:
            self._headbar_z.move(position=self._previous_positions.headbar_z)
            self._headbar_pitch.move(position=self._previous_positions.headbar_pitch)
            self._headbar_roll.move(position=self._previous_positions.headbar_roll)
            self._wheel_x.move(position=self._previous_positions.wheel_x)

        # Waits for all motors to finish moving before returning to caller.
        self.wait_until_idle()

        # Prevents further interaction with the motors without manually disabling the parking lock.
        self.park_motors()

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
        # Disables the safety motor lock before moving the motors.
        self.unpark_motors()

        # Moves the lick-port back to the mount position, while keeping all other motors in their current positions.
        self._lickport_y.move(position=self._lickport_y.mount_position)
        self._lickport_z.move(position=self._lickport_z.mount_position)
        self._lickport_x.move(position=self._lickport_x.mount_position)

        # Waits for all motors to finish moving before returning to caller.
        self.wait_until_idle()

        # Prevents further interaction with the motors without manually disabling the parking lock.
        self.park_motors()

    def generate_position_snapshot(self) -> ZaberPositions:
        """Queries the current positions of all managed Zaber motors, packages the position data into a ZaberPositions
        instance, and returns it to the caller.

        This method is used by runtime classes to update the ZaberPositions instance cached on disk for each animal.
        The method also updates the local ZaberPositions copy stored inside the class instance with the data from the
        generated snapshot. Primarily, this has to be done to support the Zaber motor shutdown sequence.
        """
        self._previous_positions = ZaberPositions(
            headbar_z=int(self._headbar_z.get_position()),
            headbar_pitch=int(self._headbar_pitch.get_position()),
            headbar_roll=int(self._headbar_roll.get_position()),
            wheel_x=int(self._wheel_x.get_position()),
            lickport_z=int(self._lickport_z.get_position()),
            lickport_x=int(self._lickport_x.get_position()),
            lickport_y=int(self._lickport_y.get_position()),
        )
        return self._previous_positions

    def wait_until_idle(self) -> None:
        """Blocks in-place while at least one motor in the managed motor group(s) is moving.

        Primarily, this method is used to issue commands to multiple motor groups and then block until all motors in
        all groups finish moving. This optimizes the overall time taken to move the motors.
        """
        # Waits for the motors to finish moving. Note, motor state polling includes the built-in delay mechanism to
        # prevent overwhelming the communication interface.
        while (
            self._headbar_z.is_busy
            or self._headbar_pitch.is_busy
            or self._headbar_roll.is_busy
            or self._wheel_x.is_busy
            or self._lickport_z.is_busy
            or self._lickport_x.is_busy
            or self._lickport_y.is_busy
        ):
            pass

    def disconnect(self) -> None:
        """Disconnects from the communication port(s) of the managed motor groups.

        This method should be called after the motors are parked (moved to their final parking position) to release
        the connection resources. If this method is not called, the runtime will NOT be able to terminate.
        """
        self._headbar.disconnect()
        self._wheel.disconnect()
        self._lickport.disconnect()

    def park_motors(self) -> None:
        """Parks all managed motor groups, preventing them from being moved via this library or Zaber GUI until
        they are unparked via the unpark_motors() command.
        """
        self._headbar_pitch.park()
        self._headbar_roll.park()
        self._headbar_z.park()
        self._wheel_x.park()
        self._lickport_x.park()
        self._lickport_y.park()
        self._lickport_z.park()

    def unpark_motors(self) -> None:
        """Unparks all managed motor groups, allowing them to be moved via this library or the Zaber GUI."""
        self._headbar_pitch.unpark()
        self._headbar_roll.unpark()
        self._headbar_z.unpark()
        self._wheel_x.unpark()
        self._lickport_x.unpark()
        self._lickport_y.unpark()
        self._lickport_z.unpark()

    @property
    def is_connected(self) -> bool:
        """Returns True if all managed motor connections are active and False if at least one connection is inactive."""
        connections = [
            self._headbar.is_connected,
            self._lickport.is_connected,
            self._wheel.is_connected,
        ]
        return all(connections)


class MicroControllerInterfaces:
    """Interfaces with the Ataraxis Micro Controller (AMC) devices used in the Mesoscope-VR data acquisition system.

    Notes:
        This class interfaces with the three AMC controllers used in the system: Actor, Sensor, and Encoder.

        Calling the class initializer does not start the microcontroller communication processes.
        Use the start() method before calling other instance methods.

        The instance reserves 3 CPU cores for running the microcontroller communication processes.

    Args:
        data_logger: The DataLogger instance to use for logging the data generated by the managed microcontrollers
            during runtime.
        microcontroller_configuration: The MesoscopeMicroControllers instance that stores the configuration
            parameters for the managed microcontrollers.

    Attributes:
        _started: Tracks whether the microcontroller communication processes are currently running.
        _configuration: Stores the managed microcontrollers' configuration parameters.
        brake: The interface that controls the electromagnetic particle brake attached to the running wheel.
        valve: The interface that controls the solenoid water valve.
        screens: The interface that controls the power state of the Virtual Reality display screens.
        _actor: The main interface for the 'Actor' Ataraxis Micro Controller (AMC) device.
        mesoscope_frame: The interface that monitors frame acquisition timestamp signals sent by the mesoscope.
        lick: The interface that monitors animal's interactions with the lick sensor.
        torque: The interface that monitors the torque applied by the animal to the running wheel when the brakes are
            on.
        _sensor: The main interface for the 'Sensor' Ataraxis Micro Controller (AMC) device.
        wheel_encoder: The interface that monitors the distance traveled by the animal on the running wheel.
        _encoder: The main interface for the 'Encoder' Ataraxis Micro Controller (AMC) device.
    """

    def __init__(self, data_logger: DataLogger, microcontroller_configuration: MesoscopeMicroControllers) -> None:
        # Tracks whether the communication processes have been started.
        self._started: bool = False

        # Caches the microcontroller configuration parameters to the instance attribute.
        self._configuration: MesoscopeMicroControllers = microcontroller_configuration

        # Converts the sensor polling frequency from milliseconds to microseconds. This value is used below to
        # initialize most sensor interfaces.
        _sensor_polling_delay: int = round(
            convert_time(
                time=self._configuration.sensor_polling_delay_ms,
                from_units=TimeUnits.MILLISECOND,
                to_units=TimeUnits.MICROSECOND,
            )
        )

        # ACTOR. Actor AMC controls the hardware that needs to be triggered by PC at irregular intervals. Most of such
        # hardware is designed to produce some form of an output: deliver water reward, engage wheel brake, etc.

        # Module interfaces:
        self.brake = BrakeInterface(
            minimum_brake_strength=self._configuration.minimum_brake_strength_g_cm,
            maximum_brake_strength=self._configuration.maximum_brake_strength_g_cm,
        )
        self.valve = ValveInterface(
            valve_calibration_data=self._configuration.valve_calibration_data,
        )
        self.screens = ScreenInterface()

        # Main interface:
        self._actor: MicroControllerInterface = MicroControllerInterface(
            controller_id=np.uint8(101),
            buffer_size=8192,
            port=self._configuration.actor_port,
            data_logger=data_logger,
            module_interfaces=(self.brake, self.valve, self.screens),
        )

        # SENSOR. Sensor AMC controls the hardware that collects data at regular intervals. This includes lick sensors,
        # torque sensors, and input TTL recorders. Critically, all managed hardware does not rely on hardware interrupt
        # logic to maintain the necessary precision.

        # Module interfaces:
        self.mesoscope_frame: TTLInterface = TTLInterface(polling_frequency=_sensor_polling_delay)
        self.lick: LickInterface = LickInterface(
            lick_threshold=self._configuration.lick_threshold_adc,
            polling_frequency=_sensor_polling_delay,
        )
        self.torque: TorqueInterface = TorqueInterface(
            baseline_voltage=self._configuration.torque_baseline_voltage_adc,
            maximum_voltage=self._configuration.torque_maximum_voltage_adc,
            sensor_capacity=self._configuration.torque_sensor_capacity_g_cm,
            polling_frequency=_sensor_polling_delay,
        )

        # Main interface:
        self._sensor: MicroControllerInterface = MicroControllerInterface(
            controller_id=np.uint8(152),
            buffer_size=8192,
            port=self._configuration.sensor_port,
            data_logger=data_logger,
            module_interfaces=(self.mesoscope_frame, self.lick, self.torque),
        )

        # ENCODER. Encoder AMC is specifically designed to interface with a quadrature encoder connected to the running
        # wheel. The encoder uses hardware interrupt logic to maintain high precision and is isolated to a separate
        # microcontroller to ensure the highest possible throughput and sensor resolution.

        # Module interfaces:
        self.wheel_encoder: EncoderInterface = EncoderInterface(
            encoder_ppr=self._configuration.wheel_encoder_ppr,
            wheel_diameter=self._configuration.wheel_diameter_cm,
            cm_per_unity_unit=self._configuration.cm_per_unity_unit,
            polling_frequency=microcontroller_configuration.wheel_encoder_polling_delay_us,
        )

        # Main interface:
        self._encoder: MicroControllerInterface = MicroControllerInterface(
            controller_id=np.uint8(203),
            buffer_size=8192,
            port=self._configuration.encoder_port,
            data_logger=data_logger,
            module_interfaces=(self.wheel_encoder,),
        )

    def __del__(self) -> None:
        """Ensures that all communication processes are terminated when the instance is garbage-collected."""
        self.stop()

    def start(self) -> None:
        """Starts the communication processes for all managed microcontrollers and configures all interfaced hardware
        modules to use the runtime parameters loaded from the acquisition system's configuration file.
        """
        # Prevents executing this method if the microcontrollers are already running.
        if self._started:
            return

        message = "Initializing Ataraxis Micro Controller (AMC) Interfaces..."
        console.echo(message=message, level=LogLevel.INFO)

        # Starts all microcontroller interfaces
        self._actor.start()
        self._sensor.start()
        self._encoder.start()

        # Wheel Encoder
        self.wheel_encoder.set_parameters(
            report_cw=np.bool(self._configuration.wheel_encoder_report_cw),
            report_ccw=np.bool(self._configuration.wheel_encoder_report_ccw),
            delta_threshold=np.uint32(self._configuration.wheel_encoder_delta_threshold_pulse),
        )

        # Screen Interface
        screen_pulse_duration: np.float64 = convert_time(
            time=self._configuration.screen_trigger_pulse_duration_ms,
            from_units="ms",
            to_units="us",
        )
        self.screens.set_parameters(pulse_duration=np.uint32(round(screen_pulse_duration)))

        # Lick Sensor
        self.lick.set_parameters(
            signal_threshold=np.uint16(self._configuration.lick_signal_threshold_adc),
            delta_threshold=np.uint16(self._configuration.lick_delta_threshold_adc),
            average_pool_size=np.uint8(self._configuration.lick_averaging_pool_size),
        )

        # Torque Sensor
        self.torque.set_parameters(
            report_ccw=np.bool(self._configuration.torque_report_ccw),
            report_cw=np.bool(self._configuration.torque_report_cw),
            signal_threshold=np.uint16(self._configuration.torque_signal_threshold_adc),
            delta_threshold=np.uint16(self._configuration.torque_delta_threshold_adc),
            averaging_pool_size=np.uint8(self._configuration.torque_averaging_pool_size),
        )

        # Mesoscope Frame TTL Recorder
        self.mesoscope_frame.set_parameters(
            averaging_pool_size=np.uint8(self._configuration.mesoscope_frame_averaging_pool_size)
        )

        # The setup procedure is complete.
        self._started = True

        message = "Ataraxis Micro Controller (AMC) Interfaces: Initialized."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def stop(self) -> None:
        """Stops all microcontroller communication processes and releases all reserved resources."""
        # Prevents stopping an already stopped VR process.
        if not self._started:
            return

        message = "Terminating Ataraxis Micro Controller (AMC) Interfaces..."
        console.echo(message=message, level=LogLevel.INFO)

        # Resets the _started tracker
        self._started = False

        # Stops all microcontroller interfaces. This also shuts down and resets all managed hardware modules.
        self._actor.stop()
        self._sensor.stop()
        self._encoder.stop()

        message = "Ataraxis Micro Controller (AMC) Interfaces: Terminated."
        console.echo(message=message, level=LogLevel.SUCCESS)


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

    # noinspection PyTypeChecker
    def __init__(
        self,
        data_logger: DataLogger,
        output_directory: Path,
    ) -> None:
        # Creates the _started flags first to avoid leaks if the initialization method fails.
        self._face_camera_started: bool = False
        self._body_cameras_started: bool = False

        # Retrieves the Mesoscope-VR system configuration parameters and saves them to class attribute to use them from
        # class methods.
        self._system_configuration = get_system_configuration()

        # FACE CAMERA. This is the high-grade scientific camera aimed at the animal's face using the hot-mirror. It is
        # a 10-gigabit 9MP camera with a red long-pass filter and has to be interfaced through the GeniCam API. Since
        # the VRPC has a 4090 with 2 hardware acceleration chips, we are using the GPU to save all of our frame data.
        self._face_camera: VideoSystem = VideoSystem(
            system_id=np.uint8(51),  # Hardcoded
            data_logger=data_logger,
            output_directory=output_directory,
            harvesters_cti_path=self._system_configuration.paths.harvesters_cti_path,
        )
        # The acquisition parameters (framerate, frame dimensions, crop offsets, etc.) are set via the SVCapture64
        # software and written to non-volatile device memory. Generally, all projects in the lab should be using the
        # same parameters.
        self._face_camera.add_camera(
            save_frames=True,  # Hardcoded
            camera_index=self._system_configuration.cameras.face_camera_index,
            camera_backend=CameraBackends.HARVESTERS,  # Hardcoded
            output_frames=False,  # Hardcoded, as using queue output requires library refactoring anyway.
            display_frames=self._system_configuration.cameras.display_face_camera_frames,
            display_frame_rate=25,  # Hardcoded
        )
        self._face_camera.add_video_saver(
            hardware_encoding=True,  # Hardcoded
            video_format=VideoFormats.MP4,  # Hardcoded
            video_codec=VideoCodecs.H265,  # Hardcoded
            preset=GPUEncoderPresets.SLOW,  # Hardcoded
            input_pixel_format=InputPixelFormats.MONOCHROME,  # Hardcoded
            output_pixel_format=OutputPixelFormats.YUV444,  # Hardcoded
            quantization_parameter=self._system_configuration.cameras.face_camera_quantization_parameter,
        )

        # LEFT CAMERA. A 1080P security camera that is mounted on the left side from the mouse's perspective
        # (viewing the left side of the mouse and the right screen). This camera is interfaced with through the OpenCV
        # backend.
        self._left_camera: VideoSystem = VideoSystem(
            system_id=np.uint8(62), data_logger=data_logger, output_directory=output_directory
        )

        # DO NOT try to force the acquisition rate. If it is not 30 (default), the video will not save.
        self._left_camera.add_camera(
            save_frames=True,  # Hardcoded
            # The only difference between left and right cameras.
            camera_index=self._system_configuration.cameras.left_camera_index,
            camera_backend=CameraBackends.OPENCV,  # Hardcoded
            output_frames=False,  # Hardcoded, as using queue output requires library refactoring anyway.
            display_frames=self._system_configuration.cameras.display_body_camera_frames,
            display_frame_rate=25,  # Hardcoded
            color=False,  # Hardcoded
        )
        self._left_camera.add_video_saver(
            hardware_encoding=True,  # Hardcoded
            video_format=VideoFormats.MP4,  # Hardcoded
            video_codec=VideoCodecs.H265,  # Hardcoded
            preset=GPUEncoderPresets.FAST,  # Hardcoded
            input_pixel_format=InputPixelFormats.MONOCHROME,  # Hardcoded
            output_pixel_format=OutputPixelFormats.YUV420,  # Hardcoded
            quantization_parameter=self._system_configuration.cameras.body_camera_quantization_parameter,
        )

        # RIGHT CAMERA. Same as the left camera, but mounted on the right side from the mouse's perspective.
        self._right_camera: VideoSystem = VideoSystem(
            system_id=np.uint8(73), data_logger=data_logger, output_directory=output_directory
        )
        # Same as above, DO NOT force acquisition rate
        self._right_camera.add_camera(
            save_frames=True,  # Hardcoded
            # The only difference between left and right cameras.
            camera_index=self._system_configuration.cameras.right_camera_index,
            camera_backend=CameraBackends.OPENCV,
            output_frames=False,  # Hardcoded, as using queue output requires library refactoring anyway.
            display_frames=self._system_configuration.cameras.display_body_camera_frames,
            display_frame_rate=25,  # Hardcoded
            color=False,  # Hardcoded
        )
        self._right_camera.add_video_saver(
            hardware_encoding=True,  # Hardcoded
            video_format=VideoFormats.MP4,  # Hardcoded
            video_codec=VideoCodecs.H265,  # Hardcoded
            preset=GPUEncoderPresets.FAST,  # Hardcoded
            input_pixel_format=InputPixelFormats.MONOCHROME,  # Hardcoded
            output_pixel_format=OutputPixelFormats.YUV420,  # Hardcoded
            quantization_parameter=self._system_configuration.cameras.body_camera_quantization_parameter,
        )

    def __del__(self) -> None:
        """Ensures all hardware resources are released when the class is garbage-collected."""
        self.stop()

    def start_face_camera(self) -> None:
        """Starts face camera frame acquisition.

        This method sets up both the frame acquisition (producer) process and the frame saver (consumer) process.
        However, the consumer process will not save any frames until the save_face_camera_frames () method is called.
        """
        # Prevents executing this method if the face camera is already running
        if self._face_camera_started:
            return

        message = "Initializing face camera frame acquisition..."
        console.echo(message=message, level=LogLevel.INFO)

        # Starts frame acquisition. Note, this does NOT start frame saving.
        self._face_camera.start()
        self._face_camera_started = True

        message = "Face camera frame acquisition: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def start_body_cameras(self) -> None:
        """Starts left and right (body) camera frame acquisition.

        This method sets up both the frame acquisition (producer) process and the frame saver (consumer) process for
        both cameras. However, the consumer processes will not save any frames until the save_body_camera_frames ()
        method is called.
        """
        # Prevents executing this method if the body cameras are already running
        if self._body_cameras_started:
            return

        message = "Initializing body cameras (left and right) frame acquisition..."
        console.echo(message=message, level=LogLevel.INFO)

        # Starts frame acquisition. Note, this does NOT start frame saving.
        self._left_camera.start()
        self._right_camera.start()
        self._body_cameras_started = True

        message = "Body cameras frame acquisition: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def save_face_camera_frames(self) -> None:
        """Starts saving the frames acquired by the face camera as a video file."""
        # Starts frame saving process
        self._face_camera.start_frame_saving()

        message = "Face camera frame saving: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def save_body_camera_frames(self) -> None:
        """Starts saving the frames acquired by the left and right body cameras as a video file."""
        # Starts frame saving process
        self._left_camera.start_frame_saving()
        self._right_camera.start_frame_saving()

        message = "Body cameras frame saving: Started."
        console.echo(message=message, level=LogLevel.SUCCESS)

    def stop(self) -> None:
        """Stops saving all camera frames and terminates the managed VideoSystems.

        This method needs to be called at the end of each runtime to release the resources reserved by the start()
        methods. Until the stop() method is called, the DataLogger instance may receive data from running
        VideoSystems, so calling this method also guarantees no VideoSystem data will be lost if the DataLogger
        process is terminated. Similarly, this guarantees the integrity of the generated video files.
        """
        # Prevents executing this method if no cameras are running.
        if not self._face_camera_started and not self._body_cameras_started:
            return

        message = "Terminating Ataraxis Video System (AVS) Interfaces..."
        console.echo(message=message, level=LogLevel.INFO)

        # Instructs all cameras to stop saving frames
        self._face_camera.stop_frame_saving()
        self._left_camera.stop_frame_saving()
        self._right_camera.stop_frame_saving()

        message = "Camera frame saving: Stopped."
        console.echo(message=message, level=LogLevel.SUCCESS)

        # Stops all cameras
        self._face_camera.stop()
        self._left_camera.stop()
        self._right_camera.stop()

        # Marks all cameras as stopped
        self._face_camera_started = False
        self._body_cameras_started = False

        message = "Video Systems: Terminated."
        console.echo(message=message, level=LogLevel.SUCCESS)

    @property
    def face_camera_log_path(self) -> Path:
        """Returns the path to the compressed .npz archive that stores the data logged by the face camera during
        runtime.
        """
        return self._face_camera.log_path

    @property
    def left_camera_log_path(self) -> Path:
        """Returns the path to the compressed .npz archive that stores the data logged by the left body camera during
        runtime.
        """
        return self._left_camera.log_path

    @property
    def right_camera_log_path(self) -> Path:
        """Returns the path to the compressed .npz archive that stores the data logged by the right body camera during
        runtime.
        """
        return self._right_camera.log_path
