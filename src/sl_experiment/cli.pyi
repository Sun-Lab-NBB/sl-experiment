from pathlib import Path

from .mesoscope_vr import (
    CRCCalculator as CRCCalculator,
    experiment_logic as experiment_logic,
    maintenance_logic as maintenance_logic,
    run_training_logic as run_training_logic,
    lick_training_logic as lick_training_logic,
    purge_failed_session as purge_failed_session,
    purge_redundant_data as purge_redundant_data,
    window_checking_logic as window_checking_logic,
    discover_zaber_devices as discover_zaber_devices,
    preprocess_session_data as preprocess_session_data,
    migrate_animal_between_projects as migrate_animal_between_projects,
)

def calculate_crc(input_string: str) -> None:
    """Calculates the CRC32-XFER checksum for the input string."""

def list_devices(errors: bool) -> None:
    """Displays information about all Zaber devices available through USB ports of the host-system."""

def generate_system_configuration_file(output_directory: str, acquisition_system: str) -> None:
    """Generates a precursor system configuration file for the target acquisition system and configures all local
    Sun lab libraries to use that file to load the acquisition system configuration data.

    This command is typically used when setting up a new data acquisition system in the lab. The system configuration
    only needs to be specified on the machine (PC) that runs the sl-experiment library and manages the acquisition
    runtime if the system uses multiple machines (PCs). Once the system configuration .yaml file is created via this
    command, editing the configuration parameters in the file will automatically take effect during all following
    runtimes.
    """

def generate_project_data_structure(project: str) -> None:
    """Generates a new project directory hierarchy on the local machine.

    This command creates new Sun lab projects. Until a project is created in this fashion, all data-acquisition and
    data-processing commands from sl-experiment library targeting the project will not work. This command is intended to
    be called on the main computer of the data-acquisition system(s) used by the project. Note, this command assumes
    that the local machine (PC) is the main PC of the data acquisition system and has a valid acquisition system
    configuration .yaml file.
    """

def generate_experiment_configuration_file(project: str, experiment: str, state_count: int, trial_count: int) -> None:
    """Generates a precursor experiment configuration .yaml file for the target experiment inside the project's
    configuration folder.

    This command assists users in creating new experiment configurations by statically resolving the structure (layout)
    of the appropriate experiment configuration file for the acquisition system of the local machine (PC). Specifically,
    the generated precursor will contain the correct number of experiment state entries initialized to nonsensical
    default value. The user needs to manually edit the configuration file to properly specify their experiment runtime
    parameters and state transitions before running the experiment. In a sense, this command acts as an 'experiment
    template' generator.
    """

def maintain_acquisition_system() -> None:
    """Exposes a terminal interface to interact with the water delivery solenoid valve and the running-wheel break.

    This CLI command is primarily designed to fill, empty, check, and, if necessary, recalibrate the solenoid valve
    used to deliver water to animals during training and experiment runtimes. Also, it is capable of locking or
    unlocking the wheel breaks, which is helpful when cleaning the wheel (after each session) and maintaining the wrap
    around the wheel surface (weekly to monthly).
    """

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

def run_experiment(
    user: str, project: str, experiment: str, animal: str, animal_weight: float, unconsumed_rewards: int
) -> None:
    """Runs the requested experiment session for the specified animal and project combination.

    Experiment runtimes are carried out after the lick and run training sessions Unlike training session commands, this
    command can be used to run different experiments. Each experiment runtime is configured via the user-defined
    configuration .yaml file, which should be stored inside the 'configuration' folder of the target project. The
    experiments are discovered by name, allowing a single project to have multiple different experiments. To create a
    new experiment configuration, use the 'sl-create-experiment' CLI command.
    """

def check_window(user: str, project: str, animal: str) -> None:
    """Runs the cranial window and surgery quality checking session for the specified animal and project combination.

    Before the animals are fully inducted (included) into a project, the quality of the surgical intervention
    (craniotomy and window implantation) is checked to ensure the animal will produce high-quality scientific data. As
    part of this process, various parameters of the Mesoscope-VR data acquisition system are also calibrated to best
    suit the animal. This command aggregates all steps necessary to verify and record the quality of the animal's window
    and to generate customized Mesoscope-VR parameters for the animal.
    """

def preprocess_session(session_path: Path) -> None:
    """Preprocesses the target session's data.

    This command aggregates all session data on the VRPC, compresses the data to optimize it for network transmission
    and storage, and transfers the data to the NAS and the BioHPC cluster. It automatically skips already completed
    processing stages as necessary to optimize runtime performance.

    Primarily, this command is intended to retry or resume failed or interrupted preprocessing runtimes.
    Preprocessing should be carried out immediately after data acquisition to optimize the acquired data for long-term
    storage and distribute it to the NAS and the BioHPC cluster for further processing and storage.
    """

def purge_data() -> None:
    """Removes all redundant data directories for ALL projects from the ScanImagePC and the VRPC.

    Redundant data purging is now executed automatically as part of data preprocessing. This command is primarily
    maintained as a fall-back option if automated data purging fails for any reason. Data purging should be carried out
    at least weekly to remove no longer necessary data from the PCs used during data acquisition.
    """

def delete_session(session_path: Path) -> None:
    """Removes ALL data of the target session from ALL data acquisition and long-term storage machines accessible to
    the host-machine.

    This is an EXTREMELY dangerous command that can potentially delete valuable data if not used well. This command is
    intended exclusively for removing failed and test sessions from all computers used in the Sun lab data acquisition
    process. Never call this command unless you know what you are doing.
    """

def migrate_animal(source: str, destination: str, animal: str) -> None:
    """Migrates all sessions for the specified animal from the source project to the target project.

    This CLI command is primarily intended to move mice from the initial 'test' project to the final experiment project
    in which they will participate. Note, the migration process determines what data to move based on the current state
    of the project data on the remote compute server. Any session that has not been moved to the server will be ignored
    during this command's runtime.
    """
