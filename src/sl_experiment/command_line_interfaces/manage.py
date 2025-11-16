"""This module provides the 'sl-manage' Command Line Interface (CLI) for managing the data accessible to the data
acquisition system managed by the host-machine.
"""

from pathlib import Path

import click
from sl_shared_assets import (
    SessionData,
)

from ..mesoscope_vr import (
    purge_session,
    preprocess_session_data,
    migrate_animal_between_projects,
)


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
@click.option(
    "-sp",
    "--session-path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    required=True,
    prompt="Enter the path to the target session directory: ",
    help="The path to the local session directory of the session to be removed.",
)
def delete_session(session_path: Path) -> None:
    """Removes ALL data of the target session from ALL data acquisition and long-term storage machines accessible to
    the host-machine.

    This is an EXTREMELY dangerous command that can potentially delete valuable data if not used well. This command is
    intended exclusively for removing failed and test sessions from all computers used in the Sun lab data acquisition
    process. Never call this command unless you know what you are doing.
    """
    session_path = Path(session_path)  # Ensures the path is wrapped into a Path object instance.

    # Restores SessionData from the cache .yaml file.
    session_data = SessionData.load(session_path=session_path)

    # Removes all data of the target session from all data acquisition and long-term storage machines accessible to the
    # host-computer
    purge_session(session_data)


@click.command()
@click.option(
    "-s",
    "--source",
    type=str,
    required=True,
    help="The name of the project from which to migrate the data.",
)
@click.option(
    "-d",
    "--destination",
    type=str,
    required=True,
    help="The name of the project to which to migrate the data.",
)
@click.option(
    "-a",
    "--animal",
    type=str,
    required=True,
    help="The ID of the animal whose data is being migrated.",
)
def migrate_animal(source: str, destination: str, animal: str) -> None:
    """Migrates all sessions for the specified animal from the source project to the target project.

    This CLI command is primarily intended to move mice from the initial 'test' project to the final experiment project
    in which they will participate. Note, the migration process determines what data to move based on the current state
    of the project data on the remote compute server. Any session that has not been moved to the server will be ignored
    during this command's runtime.
    """
    migrate_animal_between_projects(source_project=source, target_project=destination, animal=animal)
