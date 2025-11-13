"""This module provides miscellaneous assets shared by other library packages."""

import sys

from sl_shared_assets import get_system_configuration_data
from importlib_metadata import metadata as _metadata


def get_version_data() -> tuple[str, str]:
    """Determines and returns the current Python and sl-experiment versions.

    Returns:
        A tuple of two strings. The first string stores the Python version, and the second string stores the
        sl-experiment version.
    """
    # Determines the local Python version and the version of the sl-experiment library.
    sl_experiment_version = _metadata("sl-experiment")["version"]
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"  # Python version
    return python_version, sl_experiment_version


def get_animal_project(animal_id: str) -> tuple[str, ...]:
    """Scans the local project directory and returns the names of all projects that use the target animal.

    Args:
        animal_id: The unique identifier of the animal for which to discover the projects that use this animal.

    Returns:
        A tuple of project names that use the target animal.
    """
    system_configuration = get_system_configuration_data()

    return tuple(
        directory.name
        for directory in system_configuration.filesystem.root_directory.iterdir()
        if directory.is_dir() and directory.joinpath(animal_id).exists()
    )


def get_project_experiments(project: str) -> tuple[str, ...]:
    """Discovers the available experiment configuration files for the target project.

    Args:
        project: The name of the project for which to discover the experiment configurations.

    Returns:
        A tuple of experiment configurations available for the target project.
    """
    system_configuration = get_system_configuration_data()
    configuration_path = system_configuration.filesystem.root_directory.joinpath(project, "configuration")

    return tuple(configuration.stem for configuration in configuration_path.glob("*.yaml"))
