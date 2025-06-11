"""This module provides click-based Command-Line Interface (CLI) scripts that allow accessing all user-facing features
from this library through the terminal."""

from pathlib import Path

import click
from sl_shared_assets import SessionData

from .mesoscope_vr import (
    CRCCalculator,
    experiment_logic,
    maintenance_logic,
    run_training_logic,
    lick_training_logic,
    purge_redundant_data,
    window_checking_logic,
    discover_zaber_devices,
    preprocess_session_data,
)


@click.command()
@click.option(
    "-i",
    "--input_string",
    prompt="Enter the string to be checksummed: ",
    help="The string to calculate the CRC checksum for.",
)
def calculate_crc(input_string: str) -> None:
    """Calculates the CRC32-XFER checksum for the input string."""
    calculator = CRCCalculator()
    crc_checksum = calculator.string_checksum(input_string)
    click.echo(f"The CRC32-XFER checksum for the input string '{input_string}' is: {crc_checksum}.")


@click.command()
@click.option(
    "-e",
    "--errors",
    is_flag=True,
    show_default=True,
    default=False,
    help="Determines whether to display errors encountered when connecting to evaluated serial ports.",
)
def list_devices(errors: bool) -> None:
    """Displays information about all Zaber devices available through USB ports of the host-system."""
    discover_zaber_devices(silence_errors=not errors)


@click.command()
def maintain_acquisition_system() -> None:
    """Exposes a terminal interface to interact with the water delivery solenoid valve and the running wheel break.

    This CLI command is primarily designed to fill, empty, check, and, if necessary, recalibrate the solenoid valve
    used to deliver water to animals during training and experiment runtimes. Also, it is capable of locking or
    unlocking the wheel breaks, which is helpful when cleaning the wheel (after each session) and maintaining the wrap
    around the wheel surface (weekly to monthly).
    """
    maintenance_logic()


@click.command()
@click.option(
    "-u",
    "--user",
    type=str,
    required=True,
    help="The ID of the user supervising the training session.",
)
@click.option(
    "-p",
    "--project",
    type=str,
    required=True,
    help="The name of the project to which the trained animal belongs.",
)
@click.option(
    "-a",
    "--animal",
    type=str,
    required=True,
    help="The ID of the animal undergoing the lick training session.",
)
@click.option(
    "-w",
    "--animal_weight",
    type=float,
    required=True,
    help="The weight of the animal, in grams, at the beginning of the training session.",
)
@click.option(
    "-min",
    "--minimum_delay",
    type=int,
    show_default=True,
    default=6,
    help="The minimum number of seconds that has to pass between two consecutive reward deliveries during training.",
)
@click.option(
    "-max",
    "--maximum_delay",
    type=int,
    show_default=True,
    default=18,
    help="The maximum number of seconds that can pass between two consecutive reward deliveries during training.",
)
@click.option(
    "-v",
    "--maximum_volume",
    type=float,
    show_default=True,
    default=1.0,
    help="The maximum volume of water, in milliliters, that can be delivered during training.",
)
@click.option(
    "-t",
    "--maximum_time",
    type=int,
    show_default=True,
    default=20,
    help="The maximum time to run the training, in minutes.",
)
@click.option(
    "-ur",
    "--unconsumed_rewards",
    type=int,
    show_default=True,
    default=1,
    help=(
        "The maximum number of rewards that can be delivered without the animal consuming them, before reward delivery "
        "is paused. Set to 0 to disable enforcing reward consumption."
    ),
)
@click.option(
    "-r",
    "--restore_parameters",
    is_flag=True,
    show_default=True,
    default=False,
    help=(
        "Determines whether to load and use the same training parameters as used during the previous lick training "
        "session of the target animal. Note, this only overrides the maximum and minimum reward delays, all other "
        "parameters are not affected by this flag."
    ),
)
def lick_training(
    user: str,
    animal: str,
    project: str,
    animal_weight: float,
    minimum_delay: int,
    maximum_delay: int,
    maximum_volume: float,
    maximum_time: int,
    unconsumed_rewards: int,
    restore_parameters: bool,
) -> None:
    """Runs the lick training session for the specified animal and project combination.

    Lick training is the first phase of preparing the animal to run experiment runtimes in the lab, and is usually
    carried out over the first two days of head-fixed training. Primarily, this training is designed to teach the
    animal to operate the lick-port and associate licking at the port with water delivery.
    """
    lick_training_logic(
        experimenter=user,
        project_name=project,
        animal_id=animal,
        animal_weight=animal_weight,
        minimum_reward_delay=minimum_delay,
        maximum_reward_delay=maximum_delay,
        maximum_water_volume=maximum_volume,
        maximum_training_time=maximum_time,
        maximum_unconsumed_rewards=unconsumed_rewards,
        load_previous_parameters=restore_parameters,
    )


@click.command()
@click.option(
    "-u",
    "--user",
    type=str,
    required=True,
    help="The ID of the user supervising the training session.",
)
@click.option(
    "-p",
    "--project",
    type=str,
    required=True,
    help="The name of the project to which the trained animal belongs.",
)
@click.option(
    "-a",
    "--animal",
    type=str,
    required=True,
    help="The name of the animal undergoing the run training session.",
)
@click.option(
    "-w",
    "--animal_weight",
    type=float,
    required=True,
    help="The weight of the animal, in grams, at the beginning of the training session.",
)
@click.option(
    "-is",
    "--initial_speed",
    type=float,
    show_default=True,
    default=0.40,
    help="The initial speed, in centimeters per second, the animal must maintain to obtain water rewards.",
)
@click.option(
    "-id",
    "--initial_duration",
    type=float,
    show_default=True,
    default=0.40,
    help=(
        "The initial duration, in seconds, the animal must maintain above-threshold running speed to obtain water "
        "rewards."
    ),
)
@click.option(
    "-it",
    "--increase_threshold",
    type=float,
    show_default=True,
    default=0.1,
    help=(
        "The volume of water delivered to the animal, in milliliters, after which the speed and duration thresholds "
        "are increased by the specified step-sizes. This is used to make the training progressively harder for the "
        "animal over the course of the training session."
    ),
)
@click.option(
    "-ss",
    "--speed_step",
    type=float,
    show_default=True,
    default=0.05,
    help=(
        "The amount, in centimeters per second, to increase the speed threshold each time the animal receives the "
        "volume of water specified by the 'increase-threshold' parameter."
    ),
)
@click.option(
    "-ds",
    "--duration_step",
    type=float,
    show_default=True,
    default=0.05,
    help=(
        "The amount, in seconds, to increase the duration threshold each time the animal receives the volume of water "
        "specified by the 'increase-threshold' parameter."
    ),
)
@click.option(
    "-v",
    "--maximum_volume",
    type=float,
    show_default=True,
    default=1.0,
    help="The maximum volume of water, in milliliters, that can be delivered during training.",
)
@click.option(
    "-t",
    "--maximum_time",
    type=int,
    show_default=True,
    default=20,
    help="The maximum time to run the training, in minutes.",
)
@click.option(
    "-ur",
    "--unconsumed_rewards",
    type=int,
    show_default=True,
    default=1,
    help=(
        "The maximum number of rewards that can be delivered without the animal consuming them, before reward delivery "
        "is paused. Set to 0 to disable enforcing reward consumption."
    ),
)
@click.option(
    "-mit",
    "--maximum_idle_time",
    type=float,
    show_default=True,
    default=0.3,
    help=(
        "The maximum time, in seconds, the animal is allowed to maintain speed that is below the speed threshold, to"
        "still be rewarded. Set to 0 to disable allowing the animal to temporarily dip below running speed threshold."
    ),
)
@click.option(
    "-r",
    "--restore_parameters",
    is_flag=True,
    show_default=True,
    default=False,
    help=(
        "Determines whether to load and use the same training parameters as used during the previous lick training "
        "session of the target animal. Note, this only overrides the initial speed and duration thresholds, all other "
        "parameters are not affected by this flag."
    ),
)
def run_training(
    user: str,
    project: str,
    animal: str,
    animal_weight: float,
    initial_speed: float,
    initial_duration: float,
    increase_threshold: float,
    speed_step: float,
    duration_step: float,
    maximum_volume: float,
    maximum_time: int,
    unconsumed_rewards: int,
    maximum_idle_time: int,
    restore_parameters: bool,
) -> None:
    """Runs the run training session for the specified animal and project combination.

    Run training is the second phase of preparing the animal to run experiment runtimes in the lab, and is usually
    carried out over the five days following the lick training sessions. Primarily, this training is designed to teach
    the animal how to run the wheel treadmill while being head-fixed and associate getting water rewards with running
    on the treadmill. Over the course of training, the task requirements are adjusted to ensure the animal performs as
    many laps as possible during experiment sessions lasting ~60 minutes.
    """

    # Runs the training session.
    run_training_logic(
        experimenter=user,
        project_name=project,
        animal_id=animal,
        animal_weight=animal_weight,
        initial_speed_threshold=initial_speed,
        initial_duration_threshold=initial_duration,
        speed_increase_step=speed_step,
        duration_increase_step=duration_step,
        increase_threshold=increase_threshold,
        maximum_water_volume=maximum_volume,
        maximum_training_time=maximum_time,
        maximum_unconsumed_rewards=unconsumed_rewards,
        maximum_idle_time=maximum_idle_time,
        load_previous_parameters=restore_parameters,
    )


@click.command()
@click.option(
    "-u",
    "--user",
    type=str,
    required=True,
    help="The ID of the user supervising the experiment session.",
)
@click.option(
    "-p",
    "--project",
    type=str,
    required=True,
    help="The name of the project to which the trained animal belongs.",
)
@click.option(
    "-e",
    "--experiment",
    type=str,
    required=True,
    help="The name of the experiment to carry out during runtime.",
)
@click.option(
    "-a",
    "--animal",
    type=str,
    required=True,
    help="The name of the animal undergoing the experiment session.",
)
@click.option(
    "-w",
    "--animal_weight",
    type=float,
    required=True,
    help="The weight of the animal, in grams, at the beginning of the experiment session.",
)
def run_experiment(
    user: str,
    project: str,
    experiment: str,
    animal: str,
    animal_weight: float,
) -> None:
    """Runs the requested experiment session for the specified animal and project combination.

    Experiment runtimes are carried out after the lick and run training sessions Unlike training session commands, this
    command can be used to run different experiments. Each experiment runtime is configured via the user-defined
    configuration .yaml file, which should be stored inside the 'configuration' folder of the target project. The
    experiments are discovered by name, allowing a single project to have multiple different experiments. To create a
    new experiment configuration, use the 'sl-create-experiment' CLI command.
    """
    experiment_logic(
        experimenter=user,
        project_name=project,
        experiment_name=experiment,
        animal_id=animal,
        animal_weight=animal_weight,
    )


@click.command()
@click.option(
    "-p",
    "--project",
    type=str,
    required=True,
    help="The name of the project to which the trained animal belongs.",
)
@click.option(
    "-a",
    "--animal",
    type=str,
    required=True,
    help="The name of the animal undergoing the experiment session.",
)
def check_window(
    project: str,
    animal: str,
) -> None:
    """Runs the cranial window and surgery quality checking session for the specified animal and project combination.

    Before the animals are fully inducted (included) into a project, the quality of the surgical intervention
    (craniotomy and window implantation) is checked to ensure the animal will produce high-quality scientific data. As
    part of this process, various parameters of the Mesoscope-VR data acquisition system are also calibrated to best
    suit the animal. This command aggregates all steps necessary to verify and record the quality of the animal's window
    and to generate customized Mesoscope-VR parameters for the animal.
    """
    window_checking_logic(project_name=project, animal_id=animal)


@click.command()
@click.option(
    "-sp",
    "--session-path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    required=True,
    prompt="Enter the path to the target session directory: ",
    help="The path to the session directory to preprocess.",
)
def preprocess_session(session_path: Path) -> None:
    """Preprocesses the target session's data.

    This command aggregates all session data on the VRPC, compresses the data to optimize it for network transmission
    and storage, and transfers the data to the NAS and the BioHPC cluster. It automatically skips already completed
    processing stages as necessary to optimize runtime performance.

    Primarily, this command is intended to retry or resume failed or interrupted preprocessing runtimes.
    Preprocessing should be carried out immediately after data acquisition to optimize the acquired data for long-term
    storage and distribute it to the NAS and the BioHPC cluster for further processing and storage.
    """

    session_path = Path(session_path)  # Ensures the path is wrapped into a Path object instance.

    # Restores SessionData from the cache .yaml file.
    session_data = SessionData.load(session_path=session_path)
    preprocess_session_data(session_data)  # Runs the preprocessing logic.


@click.command()
def purge_data() -> None:
    """Removes all redundant data directories for ALL projects from the ScanImagePC and the VRPC.

    Redundant data purging is now executed automatically as part of data preprocessing. This command is primarily
    maintained as a fall-back option if automated data purging fails for any reason. Data purging should be carried out
    at least weekly to remove no longer necessary data from the PCs used during data acquisition.
    """
    purge_redundant_data()
