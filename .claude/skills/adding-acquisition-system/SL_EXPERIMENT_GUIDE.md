# sl-experiment Modification Guide

Detailed guide for implementing a new acquisition system in sl-experiment. This guide covers creating the system
package, implementing runtime logic, and integrating with the CLI.

---

## Prerequisites

Before starting Phase 2, ensure Phase 1 (sl-shared-assets) is complete:
- Configuration classes are defined and exported
- System is registered in `AcquisitionSystems` enum
- sl-shared-assets version has been bumped

---

## Step 1: Create System Package

Create a new package at `src/sl_experiment/<system>/` with the required modules.

### Package Structure

```
src/sl_experiment/<system>/
├── __init__.py              # Package exports
├── data_acquisition.py      # Runtime logic functions
├── data_preprocessing.py    # Post-session processing
└── tools.py                 # Utilities and config loading
```

### __init__.py

Export all public APIs from the package:

```python
"""[System] acquisition system implementation.

This package provides runtime logic, data processing, and utilities for the [System] acquisition system.
"""

from .data_acquisition import (
    # Export your logic functions here
    experiment_logic,
    # ... other logic functions
)

from .data_preprocessing import (
    preprocess_session_data,
    purge_session,
)

from .tools import (
    get_system_configuration,
)

# Export binding classes if applicable
# from .binding_classes import (
#     [System]Motors,
#     VideoSystems,
#     MicroControllerInterfaces,
# )

__all__ = [
    "experiment_logic",
    "preprocess_session_data",
    "purge_session",
    "get_system_configuration",
]
```

---

## Step 2: Implement tools.py

Create utility functions for configuration loading and system-specific helpers.

### Configuration Loading

```python
"""Utilities and configuration loading for [System] acquisition system."""

from sl_shared_assets import (
    get_system_configuration_data,
    [System]SystemConfiguration,
)
from ataraxis_base_utilities import console


def get_system_configuration() -> [System]SystemConfiguration:
    """Loads and validates the [System] system configuration.

    Retrieves the system configuration from the working directory and validates that it is the correct type for
    the [System] acquisition system.

    Returns:
        The validated [System] system configuration.

    Raises:
        TypeError: If the loaded configuration is not a [System]SystemConfiguration instance.
    """
    system_configuration = get_system_configuration_data()
    if not isinstance(system_configuration, [System]SystemConfiguration):
        message = (
            f"Expected [System]SystemConfiguration but got {type(system_configuration).__name__}. "
            f"Ensure the correct system configuration file is in the working directory."
        )
        console.error(message=message, error=TypeError)
    return system_configuration
```

### Session Type Definitions

Define the session types your system supports:

```python
from sl_shared_assets import SessionTypes

# Define which session types this system supports
[system]_sessions: tuple[str, ...] = (
    SessionTypes.EXPERIMENT,  # Use existing types or define new ones
    # Add other session types as needed
)
```

### System-Specific Data Classes

Add any helper dataclasses for managing session data:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class _[System]SessionPaths:
    """Manages filesystem paths for [System] session data.

    Attributes:
        session_path: Root path for the session data.
        raw_data_path: Path for raw acquisition data.
        processed_path: Path for processed data output.
    """

    session_path: Path
    raw_data_path: Path
    processed_path: Path

    @classmethod
    def from_session_data(cls, session_data) -> "_[System]SessionPaths":
        """Creates path manager from SessionData instance."""
        return cls(
            session_path=session_data.session_path,
            raw_data_path=session_data.raw_data.raw_data_path,
            processed_path=session_data.processed_data.processed_data_path,
        )
```

---

## Step 3: Implement data_acquisition.py

Create runtime logic functions for your system's session types.

### Basic Structure

```python
"""Runtime logic for [System] acquisition system sessions."""

from sl_shared_assets import SessionData, SessionTypes
from ataraxis_base_utilities import console
from ataraxis_time import PrecisionTimer

from .tools import get_system_configuration, _[System]SessionPaths


def experiment_logic(
    experimenter: str,
    project_name: str,
    experiment_name: str,
    animal_id: str,
    animal_weight: float,
) -> None:
    """Executes a [System] experiment session.

    This function manages the complete lifecycle of an experiment session including hardware initialization, data
    acquisition, and session finalization.

    Args:
        experimenter: Name of the experimenter running the session.
        project_name: Name of the project this session belongs to.
        experiment_name: Name of the experiment configuration to use.
        animal_id: Identifier for the animal subject.
        animal_weight: Weight of the animal in grams.
    """
    # Load system configuration
    system_config = get_system_configuration()

    # Create or load session data
    session_data = SessionData.create(
        experimenter=experimenter,
        project_name=project_name,
        animal_id=animal_id,
        session_type=SessionTypes.EXPERIMENT,
        filesystem_configuration=system_config.filesystem,
    )

    try:
        # Initialize hardware (if using binding classes)
        # hardware = _initialize_hardware(system_config)

        # Run main acquisition loop
        _run_acquisition_loop(session_data, system_config)

    except Exception as error:
        console.error(message=f"Session failed: {error}", error=RuntimeError)

    finally:
        # Cleanup and save
        session_data.save()
        # hardware.stop()


def _run_acquisition_loop(session_data: SessionData, config) -> None:
    """Main acquisition loop for experiment sessions.

    Args:
        session_data: Session data manager.
        config: System configuration.
    """
    timer = PrecisionTimer()

    # Implement your acquisition logic here
    # This varies significantly based on system requirements

    pass
```

### Hardware Binding Integration

If your system uses hardware that requires lifecycle management:

```python
from .binding_classes import [System]Hardware


def _initialize_hardware(config) -> [System]Hardware:
    """Initializes all hardware components for the session.

    Args:
        config: System configuration containing hardware parameters.

    Returns:
        Initialized hardware binding instance.
    """
    hardware = [System]Hardware(config)
    hardware.connect()
    hardware.start()
    return hardware
```

---

## Step 4: Implement binding_classes.py (if needed)

Create hardware abstraction classes if your system has hardware requiring lifecycle management.

### Binding Class Pattern

```python
"""Hardware abstraction classes for [System] acquisition system."""

from ataraxis_base_utilities import console
from ataraxis_data_structures import DataLogger


class [System]Hardware:
    """Manages hardware lifecycle for [System] system.

    This class provides a unified interface for initializing, starting, stopping, and cleaning up hardware
    components used by the [System] acquisition system.

    Attributes:
        config: System configuration containing hardware parameters.
    """

    def __init__(self, config, data_logger: DataLogger | None = None) -> None:
        """Initializes hardware connections.

        Args:
            config: System configuration with hardware parameters.
            data_logger: Optional data logger for recording hardware events.
        """
        self._config = config
        self._data_logger = data_logger
        self._started = False

        # Initialize device connections (but don't start them yet)
        # self._camera = CameraInterface(config.cameras.camera_index)
        # self._controller = ControllerInterface(config.microcontrollers.controller_port)

    def __del__(self) -> None:
        """Ensures cleanup on garbage collection."""
        self.stop()

    def connect(self) -> None:
        """Establishes connections to all hardware devices."""
        # self._camera.connect()
        # self._controller.connect()
        pass

    def start(self) -> None:
        """Starts all hardware operations.

        This method should be called after connect() to begin active hardware communication and data acquisition.
        """
        if self._started:
            return

        # self._camera.start()
        # self._controller.start()

        self._started = True

    def stop(self) -> None:
        """Stops all hardware operations gracefully.

        This method should be called to cleanly shutdown hardware before disconnecting or destroying the instance.
        """
        if not self._started:
            return

        # Stop in reverse order of start
        # self._controller.stop()
        # self._camera.stop()

        self._started = False

    def shutdown(self) -> None:
        """Performs complete shutdown and resource release."""
        self.stop()
        # Release any additional resources
        # self._camera.disconnect()
        # self._controller.disconnect()
```

---

## Step 5: Implement data_preprocessing.py

Create post-session data processing functions.

### Basic Structure

```python
"""Post-session data processing for [System] acquisition system."""

from pathlib import Path

from sl_shared_assets import SessionData, transfer_directory, delete_directory
from ataraxis_base_utilities import console

from .tools import get_system_configuration


def preprocess_session_data(
    project_name: str,
    animal_id: str,
    session_name: str,
) -> None:
    """Preprocesses a [System] session and transfers data to storage.

    This function handles all post-session processing including data format conversion, metadata extraction, and
    transfer to server and NAS storage locations.

    Args:
        project_name: Name of the project containing the session.
        animal_id: Identifier for the animal subject.
        session_name: Name of the session to preprocess.
    """
    system_config = get_system_configuration()

    # Load session data
    session_data = SessionData.load(
        project_name=project_name,
        animal_id=animal_id,
        session_name=session_name,
        filesystem_configuration=system_config.filesystem,
    )

    # Perform system-specific preprocessing
    _process_raw_data(session_data)

    # Transfer to storage locations
    _push_data(session_data, system_config)

    console.echo(message=f"Preprocessing complete for {session_name}")


def _process_raw_data(session_data: SessionData) -> None:
    """Processes raw acquisition data.

    Args:
        session_data: Session data containing paths to raw data.
    """
    # Implement system-specific processing
    # Examples: video encoding, signal processing, format conversion
    pass


def _push_data(session_data: SessionData, config) -> None:
    """Transfers processed data to server and NAS storage.

    Args:
        session_data: Session data with source paths.
        config: System configuration with destination paths.
    """
    source_path = session_data.session_path

    # Transfer to server
    server_dest = config.filesystem.server_directory / session_data.relative_path
    transfer_directory(source=source_path, destination=server_dest)

    # Transfer to NAS
    nas_dest = config.filesystem.nas_directory / session_data.relative_path
    transfer_directory(source=source_path, destination=nas_dest)


def purge_session(
    project_name: str,
    animal_id: str,
    session_name: str,
) -> None:
    """Removes a session from all storage locations.

    Args:
        project_name: Name of the project containing the session.
        animal_id: Identifier for the animal subject.
        session_name: Name of the session to purge.
    """
    system_config = get_system_configuration()

    session_data = SessionData.load(
        project_name=project_name,
        animal_id=animal_id,
        session_name=session_name,
        filesystem_configuration=system_config.filesystem,
    )

    # Delete from all locations
    delete_directory(session_data.session_path)

    server_path = system_config.filesystem.server_directory / session_data.relative_path
    if server_path.exists():
        delete_directory(server_path)

    nas_path = system_config.filesystem.nas_directory / session_data.relative_path
    if nas_path.exists():
        delete_directory(nas_path)

    console.echo(message=f"Purged session {session_name}")
```

---

## Step 6: Add Module Interfaces (if needed)

If your system uses microcontrollers with new module types, add ModuleInterface subclasses to
`src/sl_experiment/shared_components/module_interfaces.py`.

### ModuleInterface Pattern

```python
class [Module]Interface(ModuleInterface):
    """Interface for [Module] hardware module.

    Provides communication interface for the [Module] connected to an Ataraxis Micro Controller.

    Attributes:
        module_type: Unique type code identifying this module type.
        module_id: Instance ID for this module on the controller.
    """

    def __init__(
        self,
        controller: MicroControllerInterface,
        data_logger: DataLogger,
        module_id: np.uint8 = np.uint8(1),
    ) -> None:
        """Initializes the module interface.

        Args:
            controller: The microcontroller interface this module is connected to.
            data_logger: Data logger for recording module events.
            module_id: Instance ID for this module.
        """
        super().__init__(
            controller=controller,
            data_logger=data_logger,
            module_type=np.uint8(XX),  # Assign unique type code
            module_id=module_id,
            data_codes=(
                # Define data codes for this module
            ),
            error_codes=(
                # Define error codes for this module
            ),
        )

    # Implement module-specific methods
```

Update `shared_components/__init__.py` to export new interfaces.

---

## Step 7: Integrate with CLI

Modify the CLI modules to add commands for your system.

### execute.py

Add imports and commands for session execution:

```python
# Add imports at the top of execute.py
from ..<system> import (
    experiment_logic as [system]_experiment_logic,
    # ... other logic functions
)


# Add command under the appropriate group
@run.command("[system]-experiment")
@click.option("-u", "--user", required=True, help="Experimenter name")
@click.option("-p", "--project", required=True, help="Project name")
@click.option("-e", "--experiment", required=True, help="Experiment name")
@click.option("-a", "--animal", required=True, help="Animal ID")
@click.option("-w", "--weight", required=True, type=float, help="Animal weight in grams")
def run_[system]_experiment(user: str, project: str, experiment: str, animal: str, weight: float) -> None:
    """Runs a [System] experiment session."""
    [system]_experiment_logic(
        experimenter=user,
        project_name=project,
        experiment_name=experiment,
        animal_id=animal,
        animal_weight=weight,
    )
```

### manage.py

Add commands for data management:

```python
# Add imports
from ..<system> import (
    preprocess_session_data as [system]_preprocess,
    purge_session as [system]_purge,
)


@manage.command("[system]-preprocess")
@click.option("-p", "--project", required=True, help="Project name")
@click.option("-a", "--animal", required=True, help="Animal ID")
@click.option("-s", "--session", required=True, help="Session name")
def preprocess_[system](project: str, animal: str, session: str) -> None:
    """Preprocesses a [System] session."""
    [system]_preprocess(
        project_name=project,
        animal_id=animal,
        session_name=session,
    )
```

### get.py (if needed)

Add hardware discovery commands:

```python
@get.command("[system]-hardware")
def get_[system]_hardware() -> None:
    """Discovers [System] hardware devices."""
    # Implement hardware discovery
    pass
```

### mcp_servers.py (if needed)

Add MCP tools for agentic access:

```python
@get_mcp.tool()
def get_[system]_hardware_tool() -> str:
    """Discovers [System] hardware devices.

    Returns:
        Formatted string listing discovered hardware.
    """
    # Implement discovery
    return "Hardware discovery results"
```

---

## Step 8: Update pyproject.toml

Update the sl-shared-assets dependency version:

```toml
[project]
dependencies = [
    "sl-shared-assets>=X.Y.Z",  # Update to version with new configuration classes
    # ... other dependencies
]
```

---

## File Summary

| File | Action | Purpose |
|------|--------|---------|
| `<system>/__init__.py` | CREATE | Package exports |
| `<system>/tools.py` | CREATE | Configuration loading, utilities |
| `<system>/data_acquisition.py` | CREATE | Runtime logic functions |
| `<system>/data_preprocessing.py` | CREATE | Post-session processing |
| `<system>/binding_classes.py` | CREATE | Hardware abstraction (if needed) |
| `shared_components/module_interfaces.py` | MODIFY | Add ModuleInterface classes (if needed) |
| `shared_components/__init__.py` | MODIFY | Export new interfaces |
| `command_line_interfaces/execute.py` | MODIFY | Add session commands |
| `command_line_interfaces/manage.py` | MODIFY | Add management commands |
| `command_line_interfaces/get.py` | MODIFY | Add discovery commands (if needed) |
| `command_line_interfaces/mcp_servers.py` | MODIFY | Add MCP tools (if needed) |
| `pyproject.toml` | MODIFY | Update sl-shared-assets version |

---

## Validation

After implementing the system:

1. **Import test**: `python -c "from sl_experiment.<system> import experiment_logic"`
2. **CLI test**: `sl-run --help` should show new commands
3. **MyPy**: `mypy src/sl_experiment/<system>/`
4. **Integration test**: Run a test session with mock or real hardware
