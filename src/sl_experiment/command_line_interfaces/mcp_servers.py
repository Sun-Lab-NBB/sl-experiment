"""Provides MCP servers for agentic interaction with sl-experiment CLI functionality.

This module exposes tools from the 'sl-get' and 'sl-manage' CLI groups through the Model Context Protocol (MCP),
enabling AI agents to programmatically interact with data acquisition system features.
"""

from typing import Literal
from pathlib import Path

from natsort_rs import natsort as natsorted  # type: ignore[import-untyped]
from sl_shared_assets import SessionData, get_system_configuration_data
from mcp.server.fastmcp import FastMCP

from ..mesoscope_vr import (
    CRCCalculator,
    purge_session,
    get_zaber_devices_info,
    preprocess_session_data,
    migrate_animal_between_projects,
)
from ..shared_components import get_project_experiments

# Initializes the MCP server for sl-get tools.
get_mcp = FastMCP(name="sl-experiment-get", json_response=True)

# Initializes the MCP server for sl-manage tools.
manage_mcp = FastMCP(name="sl-experiment-manage", json_response=True)


@get_mcp.tool()
def get_zaber_devices_tool() -> str:
    """Identifies Zaber devices accessible to the data acquisition system.

    Scans all available serial ports and returns a formatted table containing port, device, and axis information
    for all discovered Zaber motor controllers.

    Notes:
        Connection errors encountered during scanning are logged at DEBUG level and do not interrupt the discovery
        process. Ports with connection errors are listed as having "No Devices".
    """
    try:
        return get_zaber_devices_info()
    except Exception as exception:
        return f"Error: {exception}"


@get_mcp.tool()
def get_projects_tool() -> str:
    """Lists all projects accessible to the data acquisition system.

    Returns:
        A comma-separated list of project names, or a message indicating no projects are configured.
    """
    try:
        system_configuration = get_system_configuration_data()
        projects = natsorted(
            [
                directory.name
                for directory in system_configuration.filesystem.root_directory.iterdir()
                if directory.is_dir() and not directory.name.startswith(".")
            ]
        )
    except Exception as exception:
        return f"Error: {exception}"
    else:
        if projects:
            return f"Projects: {', '.join(projects)}"
        return f"No projects configured for {system_configuration.name} data acquisition system."


@get_mcp.tool()
def get_experiments_tool(project: str) -> str:
    """Lists experiment configurations available for a specific project.

    Args:
        project: The name of the project for which to discover experiment configurations.

    Returns:
        A comma-separated list of experiment names, or a message indicating no experiments are configured.
    """
    try:
        system_configuration = get_system_configuration_data()
        experiments = get_project_experiments(
            project=project,
            filesystem_configuration=system_configuration.filesystem,
        )
    except Exception as exception:
        return f"Error: {exception}"
    else:
        if experiments:
            return f"Experiments for {project}: {', '.join(experiments)}"
        return f"No experiments configured for {project} project."


@get_mcp.tool()
def get_checksum_tool(input_string: str) -> str:
    """Calculates the CRC32-XFER checksum for the input string.

    Args:
        input_string: The string for which to compute the checksum.

    Returns:
        The computed CRC32-XFER checksum value.
    """
    try:
        calculator = CRCCalculator()
        checksum = calculator.string_checksum(input_string)
    except Exception as exception:
        return f"Error: {exception}"
    else:
        return f"CRC32-XFER checksum for '{input_string}': {checksum}"


@manage_mcp.tool()
def preprocess_session_tool(session_path: str) -> str:
    """Preprocesses a session's data stored on the data acquisition system's host machine.

    Args:
        session_path: The absolute path to the session directory to preprocess. The session must be located
            inside the root directory of the data acquisition system.

    Returns:
        A success message upon completion, or an error description if preprocessing fails.
    """
    try:
        path = Path(session_path)
        system_configuration = get_system_configuration_data()

        # Validates that the session is stored locally.
        if not path.is_relative_to(system_configuration.filesystem.root_directory):
            return (
                f"Error: Session directory must be inside the root directory of the "
                f"{system_configuration.name} data acquisition system "
                f"({system_configuration.filesystem.root_directory})."
            )

        session_data = SessionData.load(session_path=path)
        preprocess_session_data(session_data)
    except Exception as exception:
        return f"Error: {exception}"
    else:
        return f"Session preprocessed: {session_path}"


@manage_mcp.tool()
def delete_session_tool(session_path: str, confirm_deletion: bool = False) -> str:
    """Removes a session's data from all storage locations accessible to the data acquisition system.

    Important:
        This operation is irreversible and removes data from all machines and long-term storage destinations.
        The AI agent MUST warn the user about the consequences of this action before calling this tool with
        confirm_deletion=True.

    Args:
        session_path: The absolute path to the session directory to delete. The session must be located
            inside the root directory of the data acquisition system.
        confirm_deletion: Safety parameter that must be explicitly set to True to proceed with deletion.
            When False (the default), the tool returns a warning message instead of deleting data.

    Returns:
        A success message upon completion, a safety warning if 'confirm_deletion' is False, or an error description
        if deletion fails.
    """
    # Enforces explicit confirmation before proceeding with deletion.
    if not confirm_deletion:
        return (
            "Error: Session deletion requires explicit confirmation. Set confirm_deletion=True to proceed. "
            "WARNING: This operation permanently removes the session's data from all machines and long-term "
            "storage destinations accessible to the data acquisition system. This action cannot be undone."
        )

    try:
        path = Path(session_path)
        system_configuration = get_system_configuration_data()

        # Validates that the session is stored locally.
        if not path.is_relative_to(system_configuration.filesystem.root_directory):
            return (
                f"Error: Session directory must be inside the root directory of the "
                f"{system_configuration.name} data acquisition system "
                f"({system_configuration.filesystem.root_directory})."
            )

        session_data = SessionData.load(session_path=path)
        purge_session(session_data)
    except Exception as exception:
        return f"Error: {exception}"
    else:
        return f"Session deleted: {session_path}"


@manage_mcp.tool()
def migrate_animal_tool(source_project: str, destination_project: str, animal_id: str) -> str:
    """Transfers all sessions for an animal from one project to another.

    Args:
        source_project: The name of the project from which to migrate the data.
        destination_project: The name of the project to which to migrate the data.
        animal_id: The ID of the animal whose session data to migrate.

    Returns:
        A success message upon completion, or an error description if migration fails.
    """
    try:
        migrate_animal_between_projects(
            source_project=source_project,
            target_project=destination_project,
            animal=animal_id,
        )
    except Exception as exception:
        return f"Error: {exception}"
    else:
        return f"Animal {animal_id} migrated: {source_project} -> {destination_project}"


def run_get_server(transport: Literal["stdio", "sse", "streamable-http"] = "stdio") -> None:
    """Starts the sl-get MCP server with the specified transport.

    Args:
        transport: The transport protocol to use. Supported values are 'stdio' for standard input/output
            communication (recommended for Claude Desktop integration), 'sse' for Server-Sent Events,
            and 'streamable-http' for HTTP-based communication.
    """
    get_mcp.run(transport=transport)


def run_manage_server(transport: Literal["stdio", "sse", "streamable-http"] = "stdio") -> None:
    """Starts the sl-manage MCP server with the specified transport.

    Args:
        transport: The transport protocol to use. Supported values are 'stdio' for standard input/output
            communication (recommended for Claude Desktop integration), 'sse' for Server-Sent Events,
            and 'streamable-http' for HTTP-based communication.
    """
    manage_mcp.run(transport=transport)
