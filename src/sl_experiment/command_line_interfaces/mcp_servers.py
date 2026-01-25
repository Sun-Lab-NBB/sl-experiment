"""Provides MCP servers for agentic interaction with sl-experiment CLI functionality.

This module exposes tools from the 'sl-get' and 'sl-manage' CLI groups through the Model Context Protocol (MCP),
enabling AI agents to programmatically interact with data acquisition system features.
"""

import os
import uuid
from typing import Literal
from pathlib import Path
import contextlib

from natsort_rs import natsort as natsorted  # type: ignore[import-untyped]
from sl_shared_assets import (
    SessionData,
    GasPuffTrial,
    TaskTemplate,
    ExperimentState,
    WaterRewardTrial,
    MesoscopeExperimentConfiguration,
    get_task_templates_directory,
    get_system_configuration_data,
    create_experiment_configuration,
)
from mcp.server.fastmcp import FastMCP
from ataraxis_base_utilities import ensure_directory_exists

from ..mesoscope_vr import (
    CRCCalculator,
    purge_session,
    get_zaber_devices_info,
    preprocess_session_data,
    set_zaber_device_setting,
    get_zaber_device_settings,
    migrate_animal_between_projects,
    validate_zaber_device_configuration,
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


@get_mcp.tool()
def get_zaber_device_settings_tool(port: str, device_index: int) -> str:
    """Reads configuration settings from a Zaber device's non-volatile memory.

    Args:
        port: Serial port path (e.g., "/dev/ttyUSB0").
        device_index: Zero-based index in the daisy-chain (0 = closest to USB port).

    Returns:
        A formatted string containing device settings including labels, positions, flags, and motion limits.
    """
    try:
        settings = get_zaber_device_settings(port=port, device_index=device_index)
    except Exception as exception:
        return f"Error: {exception}"
    else:
        return (
            f"Device: {settings.device_label or '(not set)'} | Axis: {settings.axis_label or '(not set)'} | "
            f"Checksum: {settings.checksum} | Shutdown: {settings.shutdown_flag} | Unsafe: {settings.unsafe_flag} | "
            f"Park: {settings.park_position} | Maintenance: {settings.maintenance_position} | "
            f"Mount: {settings.mount_position} | Limits: [{settings.limit_min}, {settings.limit_max}] | "
            f"Position: {settings.current_position}"
        )


@get_mcp.tool()
def set_zaber_device_setting_tool(
    port: str,
    device_index: int,
    setting: str,
    value: str,
    *,
    confirm: bool = False,
) -> str:
    """Writes a configuration setting to a Zaber device's non-volatile memory.

    Important:
        This operation modifies hardware non-volatile memory. The AI agent MUST show the user the current value
        and proposed change before calling with confirm=True.

    Args:
        port: Serial port path (e.g., "/dev/ttyUSB0").
        device_index: Zero-based index in the daisy-chain (0 = closest to USB port).
        setting: Setting name. Valid options are park_position, maintenance_position, mount_position,
            unsafe_flag, shutdown_flag, device_label, and axis_label.
        value: Value to write. Use integer strings for positions and flags, regular strings for labels.
        confirm: Must be True to execute the write operation. When False, returns a preview without modifying hardware.

    Returns:
        Success message with old and new values, or a preview message if confirm is False.
    """
    if not confirm:
        try:
            settings = get_zaber_device_settings(port=port, device_index=device_index)
        except Exception as exception:
            return f"Error: {exception}"
        else:
            current_values = {
                "park_position": settings.park_position,
                "maintenance_position": settings.maintenance_position,
                "mount_position": settings.mount_position,
                "unsafe_flag": settings.unsafe_flag,
                "shutdown_flag": settings.shutdown_flag,
                "device_label": settings.device_label,
                "axis_label": settings.axis_label,
            }
            if setting not in current_values:
                return f"Error: Invalid setting '{setting}'. Valid: {', '.join(sorted(current_values.keys()))}"
            current = current_values[setting]
            return f"Preview: {setting} would change from '{current}' to '{value}'. Set confirm=True to apply."

    try:
        # Converts value to appropriate type based on setting.
        if setting in {"park_position", "maintenance_position", "mount_position", "unsafe_flag", "shutdown_flag"}:
            typed_value: int | str = int(value)
        else:
            typed_value = value

        result = set_zaber_device_setting(
            port=port,
            device_index=device_index,
            setting=setting,
            value=typed_value,
        )
    except Exception as exception:
        return f"Error: {exception}"
    else:
        return f"Success: {result}"


@get_mcp.tool()
def validate_zaber_configuration_tool(port: str, device_index: int) -> str:
    """Validates a Zaber device's configuration for use with the binding library.

    Args:
        port: Serial port path (e.g., "/dev/ttyUSB0").
        device_index: Zero-based index in the daisy-chain (0 = closest to USB port).

    Returns:
        A validation report including checksum verification, position bounds checking, and any errors or warnings.
    """
    try:
        result = validate_zaber_device_configuration(port=port, device_index=device_index)
        status = "VALID" if result.is_valid else "INVALID"
        parts = [
            f"Status: {status} | Checksum: {'OK' if result.checksum_valid else 'FAIL'} | "
            f"Positions: {'OK' if result.positions_valid else 'FAIL'}"
        ]

        if result.errors:
            parts.append(f"Errors: {'; '.join(result.errors)}")
        if result.warnings:
            parts.append(f"Warnings: {'; '.join(result.warnings)}")

        return " | ".join(parts)
    except Exception as exception:
        return f"Error: {exception}"


@get_mcp.tool()
def check_mount_accessibility_tool(path: str) -> str:
    """Verifies that a filesystem path is accessible and writable.

    Checks whether the specified path exists, is a mount point, and supports write operations. Use this to verify
    SMB/NFS mounts are properly configured before running acquisition sessions.

    Args:
        path: Filesystem path to verify (e.g., "/mnt/server/data").

    Returns:
        Status message indicating existence, mount status, write capability, and any errors.
    """
    try:
        target = Path(path)

        # Checks path existence.
        if not target.exists():
            return f"Path: {path} | Exists: No | Mount: N/A | Writable: N/A | Status: FAIL"

        # Checks if path is a mount point.
        is_mount = os.path.ismount(path)

        # Tests write capability by creating and removing a temporary file.
        writable = False
        write_error = None
        try:
            test_file = target / f".mount_test_{uuid.uuid4().hex[:8]}"
            test_file.write_text("test")
            test_file.unlink()
            writable = True
        except PermissionError:
            write_error = "Permission denied"
        except OSError as os_error:
            write_error = str(os_error)

        mount_str = "Yes" if is_mount else "No"
        write_str = "Yes" if writable else "No"
        status = "OK" if writable else "FAIL"
        check_result = f"Path: {path} | Exists: Yes | Mount: {mount_str} | Writable: {write_str} | Status: {status}"

        if write_error:
            check_result += f" | Error: {write_error}"

    except Exception as exception:
        return f"Error: {exception}"
    else:
        return check_result


@get_mcp.tool()
def check_system_mounts_tool() -> str:
    """Verifies all filesystem paths in the system configuration are accessible and writable.

    Reads the active system configuration and checks each filesystem path (root_directory, server_directory,
    nas_directory, and system-specific directories like mesoscope_directory) for existence, mount status, and
    write capability.

    Returns:
        A formatted report showing the status of each configured filesystem path with a summary line.
    """

    def check_path(name: str, directory: Path) -> str:
        """Checks a single path and returns a status line."""
        path_str = str(directory)
        if not directory or path_str in ("", "."):
            return f"{name}: (not configured)"

        if not directory.exists():
            return f"{name}: {path_str} | Exists: No | FAIL"

        is_mount = os.path.ismount(path_str)
        mount_str = "Yes" if is_mount else "No"

        # Tests write capability.
        writable = False
        with contextlib.suppress(Exception):
            test_file = directory / f".mount_test_{uuid.uuid4().hex[:8]}"
            test_file.write_text("test")
            test_file.unlink()
            writable = True

        write_str = "Yes" if writable else "No"
        status = "OK" if writable else "FAIL"
        return f"{name}: {path_str} | Mount: {mount_str} | Writable: {write_str} | {status}"

    try:
        system_config = get_system_configuration_data()
        filesystem = system_config.filesystem

        results = [
            f"System: {system_config.name}",
            check_path(name="root_directory", directory=filesystem.root_directory),
            check_path(name="server_directory", directory=filesystem.server_directory),
            check_path(name="nas_directory", directory=filesystem.nas_directory),
        ]

        # Adds system-specific directories (mesoscope has mesoscope_directory).
        if hasattr(filesystem, "mesoscope_directory"):
            results.append(check_path(name="mesoscope_directory", directory=filesystem.mesoscope_directory))

        # Computes summary statistics.
        fail_count = sum(1 for r in results[1:] if "FAIL" in r)
        ok_count = sum(1 for r in results[1:] if "OK" in r)
        not_configured = sum(1 for r in results[1:] if "not configured" in r)

        results.append(f"Summary: {ok_count} OK, {fail_count} FAIL, {not_configured} not configured")

        return "\n".join(results)
    except Exception as exception:
        return f"Error: {exception}"


@get_mcp.tool()
def get_experiment_info_tool(project: str, experiment: str) -> str:
    """Retrieves detailed information about an experiment configuration.

    Reads the experiment configuration YAML file and returns a summary of its structure including cues, segments,
    trial structures, and experiment states.

    Args:
        project: The name of the project containing the experiment.
        experiment: The name of the experiment configuration (without .yaml extension).

    Returns:
        A formatted summary of the experiment configuration, or an error message if the file cannot be read.
    """
    try:
        system_configuration = get_system_configuration_data()
        config_path = system_configuration.filesystem.root_directory.joinpath(
            project, "configuration", f"{experiment}.yaml"
        )

        if not config_path.exists():
            return f"Error: Experiment '{experiment}' not found in project '{project}'."

        experiment_config = MesoscopeExperimentConfiguration.from_yaml(file_path=config_path)

        # Builds the summary.
        cue_info = ", ".join([f"{c.name}(code={c.code})" for c in experiment_config.cues])
        segment_info = ", ".join([s.name for s in experiment_config.segments])

        trial_info_parts = []
        for name, trial in experiment_config.trial_structures.items():
            trial_type = "lick" if isinstance(trial, WaterRewardTrial) else "occupancy"
            trial_info_parts.append(f"{name}({trial_type})")
        trial_info = ", ".join(trial_info_parts)

        state_info_parts = []
        for name, state in experiment_config.experiment_states.items():
            state_info_parts.append(f"{name}(code={state.experiment_state_code}, duration={state.state_duration_s}s)")
        state_info = ", ".join(state_info_parts)

    except Exception as exception:
        return f"Error: {exception}"
    else:
        return (
            f"Experiment: {experiment} | Unity scene: {experiment_config.unity_scene_name} | "
            f"Cues: [{cue_info}] | Segments: [{segment_info}] | "
            f"Trials: [{trial_info}] | States: [{state_info}]"
        )


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
def delete_session_tool(session_path: str, *, confirm_deletion: bool = False) -> str:
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


@manage_mcp.tool()
def create_project_tool(project: str) -> str:
    """Creates a new project directory structure for the data acquisition system.

    Creates the project directory and its configuration subdirectory under the system's root directory. If the project
    already exists, returns an informational message without modifying anything.

    Args:
        project: The name of the project to create.

    Returns:
        A success message if the project was created, or an informational message if it already exists.
    """
    try:
        system_configuration = get_system_configuration_data()
        project_path = system_configuration.filesystem.root_directory.joinpath(project)
        config_path = project_path.joinpath("configuration")

        if project_path.exists():
            return f"Project '{project}' already exists at {project_path}"

        ensure_directory_exists(config_path)

    except Exception as exception:
        return f"Error: {exception}"
    else:
        return f"Project created: {project} at {project_path}"


@manage_mcp.tool()
def create_experiment_config_tool(
    project: str,
    experiment: str,
    template: str,
    state_count: int = 1,
) -> str:
    """Creates an experiment configuration from a task template.

    Generates a new experiment configuration file using the specified task template. The configuration includes VR
    structure from the template (cues, segments, trials) and generates experiment states with default guidance
    parameters. Trial-specific parameters use sensible defaults and should be customized via YAML editing.

    Args:
        project: The name of the project for which to create the experiment.
        experiment: The name for the new experiment configuration (used as filename without .yaml extension).
        template: The name of the task template to use (filename without .yaml extension).
        state_count: The number of experiment states to generate. Defaults to 1.

    Returns:
        A success message with the file path, or an error description if creation fails.
    """
    try:
        system_configuration = get_system_configuration_data()
        project_path = system_configuration.filesystem.root_directory.joinpath(project)
        file_path = project_path.joinpath("configuration", f"{experiment}.yaml")

        # Validates project exists.
        if not project_path.exists():
            return f"Error: Project '{project}' does not exist. Use create_project_tool to create it first."

        # Checks if experiment already exists.
        if file_path.exists():
            return f"Error: Experiment '{experiment}' already exists in project '{project}'."

        # Loads the task template.
        templates_dir = get_task_templates_directory()
        template_path = templates_dir.joinpath(f"{template}.yaml")
        if not template_path.exists():
            available = sorted([f.stem for f in templates_dir.glob("*.yaml")])
            return (
                f"Error: Template '{template}' not found. "
                f"Available templates: {', '.join(available) if available else 'none'}"
            )

        task_template = TaskTemplate.from_yaml(file_path=template_path)

        # Creates the experiment configuration.
        experiment_configuration = create_experiment_configuration(
            template=task_template,
            system=system_configuration.name,
            unity_scene_name=template,
        )

        # Determines trial type counts for guidance parameters.
        water_reward_count = sum(
            1 for t in experiment_configuration.trial_structures.values() if isinstance(t, WaterRewardTrial)
        )
        gas_puff_count = sum(
            1 for t in experiment_configuration.trial_structures.values() if isinstance(t, GasPuffTrial)
        )

        # Generates experiment states with guidance parameters.
        for state_num in range(state_count):
            state_name = f"state_{state_num + 1}"
            experiment_configuration.experiment_states[state_name] = ExperimentState(
                experiment_state_code=state_num + 1,
                system_state_code=0,
                state_duration_s=60,
                supports_trials=True,
                reinforcing_initial_guided_trials=3 if water_reward_count > 0 else 0,
                reinforcing_recovery_failed_threshold=9 if water_reward_count > 0 else 0,
                reinforcing_recovery_guided_trials=3 if water_reward_count > 0 else 0,
                aversive_initial_guided_trials=3 if gas_puff_count > 0 else 0,
                aversive_recovery_failed_threshold=9 if gas_puff_count > 0 else 0,
                aversive_recovery_guided_trials=3 if gas_puff_count > 0 else 0,
            )

        experiment_configuration.to_yaml(file_path=file_path)

    except Exception as exception:
        return f"Error: {exception}"
    else:
        return f"Experiment created: {experiment} from template '{template}' at {file_path}"


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
