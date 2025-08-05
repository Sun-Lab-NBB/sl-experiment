def get_version_data() -> tuple[str, str]:
    """Determines and returns the current Python and sl-experiment versions as a string of two tuples.

    The first element of the returned tuple is the Python version, while the second element is the sl-experiment
    version.
    """

def get_animal_project(animal_id: str) -> list[str]:
    """Scans the root project directory on the local machine and returns all project names that contain the given
    animal ID.

    Primarily, this worker function is used to prevent the user from assigning the animal to more than a single project.
    It is also used to help the user correctly resolve the name of the project to which the animal is currently
    assigned.

    Args:
        animal_id: The ID of the animal for which to search for project assignments.

    Returns:
        A list of project names that contain the given animal ID.
    """

def get_project_experiments(project: str) -> list[str]:
    """Scans the root target project directory for available experiment configuration files and returns their names as
    a list.

    This worker function is used to help users discover available experiment configurations for each project.

    Args:
        project: The name of the target project for which to search for experiment configurations.

    Returns:
        A list of experiment configurations available for the target project.
    """
