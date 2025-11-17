"""This module provides the 'sl-run' Command Line Interface (CLI) for running the data acquisition session and
maintenance runtimes supported by the data acquisition system managed by the host-machine.
"""

import click

from ..mesoscope_vr import (
    experiment_logic,
    maintenance_logic,
    run_training_logic,
    lick_training_logic,
    window_checking_logic,
)


@click.command()
def maintain_acquisition_system() -> None:
    """Exposes a terminal interface to interact with the water delivery solenoid valve and the running-wheel break.

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
    default=1.10,
    help="The initial speed, in centimeters per second, the animal must maintain to obtain water rewards.",
)
@click.option(
    "-id",
    "--initial_duration",
    type=float,
    show_default=True,
    default=1.10,
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
    default=0.05,
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
    default=0.1,
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
    default=0.1,
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
    default=40,
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
    default=0.5,
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
def run_experiment(
    user: str, project: str, experiment: str, animal: str, animal_weight: float, unconsumed_rewards: int
) -> None:
    """Runs the requested experiment session for the specified animal and project combination.

    Experiment runtimes are carried out after the lick and run training sessions Unlike training session commands, this
    command can be used to run different experiments. Each experiment runtime is configured via the user-defined
    configuration .yaml file, which should be stored inside the 'configuration' directory of the target project. The
    experiments are discovered by name, allowing a single project to have multiple different experiments. To create a
    new experiment configuration, use the 'sl-create-experiment' CLI command.
    """
    experiment_logic(
        experimenter=user,
        project_name=project,
        experiment_name=experiment,
        animal_id=animal,
        animal_weight=animal_weight,
        maximum_unconsumed_rewards=unconsumed_rewards,
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
    "-a",
    "--animal",
    type=str,
    required=True,
    help="The name of the animal undergoing the experiment session.",
)
def check_window(
    user: str,
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
    window_checking_logic(experimenter=user, project_name=project, animal_id=animal)
