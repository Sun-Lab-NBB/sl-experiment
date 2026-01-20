---
name: adding-acquisition-system
description: >-
  Guides agents through adding support for new data acquisition systems in sl-experiment and sl-shared-assets. Covers
  configuration dataclass creation, registry updates, CLI integration, and skill modifications. Use when implementing
  a new acquisition system, extending the framework, or understanding the system architecture.
---

# Adding Acquisition System

Guides the implementation of new data acquisition systems across the Sun Lab codebase. This skill provides a roadmap
for extending sl-shared-assets (configuration) and sl-experiment (runtime) to support new hardware systems.

---

## Core Requirements

Every acquisition system shares these infrastructure requirements:

| Requirement              | Purpose                                              |
|--------------------------|------------------------------------------------------|
| Server storage           | Long-term hot storage for processed data             |
| NAS storage              | Archival/cold storage backup                         |
| Acquisition PC           | At least one PC running the acquisition system       |
| Configuration system     | YAML-based system configuration via sl-shared-assets |
| Experiment configuration | Trial structures and interface zones (REQUIRED)      |
| Session management       | SessionData structures for data organization         |

### System-Specific Flexibility

Each acquisition system independently defines:

| Component              | Description                                                         |
|------------------------|---------------------------------------------------------------------|
| Data collection tool   | Two-photon mesoscope, widefield imaging, electrophysiology, etc.    |
| PC configuration       | Single PC, multi-PC with separate imaging workstation, etc.         |
| Hardware requirements  | Cameras, microcontrollers, motors, sensors (any combination)        |
| Runtime approach       | VR-based tasks using Unity (currently required)                     |
| Session types          | Whatever session types make sense for the system's workflow         |
| CLI commands           | Whatever commands make sense for the system's workflow              |

The mesoscope-VR system is a reference implementation. Use applicable patterns and shared assets, but design each
system based on its actual requirements.

---

## Implementation Phases

Adding a new acquisition system requires changes across two repositories in a specific order.

| Phase | Repository       | Purpose                           | Guide                                                  |
|-------|------------------|-----------------------------------|--------------------------------------------------------|
| 1     | sl-shared-assets | Define configuration dataclasses  | [SL_SHARED_ASSETS_GUIDE.md](SL_SHARED_ASSETS_GUIDE.md) |
| 2     | sl-experiment    | Implement runtime logic and CLI   | [SL_EXPERIMENT_GUIDE.md](SL_EXPERIMENT_GUIDE.md)       |
| 3     | sl-experiment    | Update acquisition-system-setup   | [Skill Updates](#phase-3-skill-updates)                |

Phase 1 MUST be completed before Phase 2. The sl-experiment package depends on configuration classes defined in
sl-shared-assets.

---

## Phase 1: Configuration (sl-shared-assets)

Read [SL_SHARED_ASSETS_GUIDE.md](SL_SHARED_ASSETS_GUIDE.md) for detailed instructions.

### Files to Modify

| File                                       | Action | Purpose                               |
|--------------------------------------------|--------|---------------------------------------|
| `configuration/<system>_configuration.py`  | CREATE | System-specific configuration classes |
| `configuration/configuration_utilities.py` | MODIFY | Register system in registries         |
| `configuration/__init__.py`                | MODIFY | Export new configuration classes      |
| `__init__.py`                              | MODIFY | Export to top-level API               |
| `data_classes/runtime_data.py`             | MODIFY | Add system-specific descriptors       |
| `data_classes/__init__.py`                 | MODIFY | Export new data classes               |
| `pyproject.toml`                           | MODIFY | Bump version number                   |

### Configuration Class Structure

Every system needs `[System]SystemConfiguration` with nested dataclasses for its hardware:

```
[System]SystemConfiguration (YamlConfig)
├── [System]FileSystem        # REQUIRED: Storage paths (root, server, NAS)
├── [System]Cameras           # If system uses cameras
├── [System]MicroControllers  # If system uses microcontrollers
├── [System]ExternalAssets    # If system uses motors, network devices, etc.
└── [System]GoogleSheets      # If system logs to Google Sheets
```

### Experiment Configuration (REQUIRED)

Every system MUST define `[System]ExperimentConfiguration` for structured experiments. All valid experiments use the
experiment configuration system with trials and interface zones. Systems reuse the VR building blocks from
`vr_configuration.py` (Cue, Segment, VREnvironment, TrialStructure, TaskTemplate) to define corridor-based behavioral
tasks that run in Unity.

### Registry Updates

After creating configuration classes, register them in `configuration_utilities.py`:

1. Add entry to `AcquisitionSystems` enum
2. Modify `SystemConfiguration` type alias to include new class
3. Modify `ExperimentConfiguration` type alias to include new class
4. Add entry to `_SYSTEM_CONFIG_CLASSES` dictionary
5. Create factory function `_create_<system>_experiment_config()`
6. Add entry to `_EXPERIMENT_CONFIG_FACTORIES` dictionary

---

## Phase 2: Implementation (sl-experiment)

Read [SL_EXPERIMENT_GUIDE.md](SL_EXPERIMENT_GUIDE.md) for detailed instructions.

### Files to Modify

| Location                                           | Action | Purpose                            |
|----------------------------------------------------|--------|------------------------------------|
| `src/sl_experiment/<system>/`                      | CREATE | New system package                 |
| `src/sl_experiment/<system>/__init__.py`           | CREATE | Export logic functions             |
| `src/sl_experiment/<system>/binding_classes.py`    | CREATE | Hardware abstraction (if needed)   |
| `src/sl_experiment/<system>/data_acquisition.py`   | CREATE | Session runtime logic              |
| `src/sl_experiment/<system>/data_preprocessing.py` | CREATE | Post-session processing            |
| `src/sl_experiment/<system>/tools.py`              | CREATE | Utilities and config loading       |
| `command_line_interfaces/execute.py`               | MODIFY | Add session commands               |
| `command_line_interfaces/get.py`                   | MODIFY | Add discovery commands (if needed) |
| `command_line_interfaces/manage.py`                | MODIFY | Add management commands            |
| `command_line_interfaces/mcp_servers.py`           | MODIFY | Add MCP tools (if needed)          |
| `shared_components/module_interfaces.py`           | MODIFY | Add ModuleInterface classes        |
| `shared_components/__init__.py`                    | MODIFY | Export new interfaces              |
| `pyproject.toml`                                   | MODIFY | Update sl-shared-assets version    |

### Minimum Package Structure

```
src/sl_experiment/<system>/
├── __init__.py              # Exports for the system
├── data_acquisition.py      # Runtime logic functions
├── data_preprocessing.py    # Post-session data processing
└── tools.py                 # Utilities and config loading
```

Additional modules depend on system requirements:

| Module               | Include When                                         |
|----------------------|------------------------------------------------------|
| `binding_classes.py` | System has hardware that needs lifecycle management  |
| `runtime_ui.py`      | System needs real-time control GUI during sessions   |
| `maintenance_ui.py`  | System needs hardware maintenance interface          |
| `visualizers.py`     | System needs real-time data visualization            |
| `*_bindings.py`      | System has device-specific drivers (e.g., Zaber)     |

### CLI Integration

Currently, CLI modules in `command_line_interfaces/` directly import from `mesoscope_vr`. To add a new system, you
must add imports and commands for the new system alongside the existing mesoscope commands. Each system's commands
should be clearly organized within the CLI files.

---

## Phase 3: Skill Updates

After implementing the new system, update the acquisition-system-setup skill.

### Files to Modify

| File                                                            | Change                                |
|-----------------------------------------------------------------|---------------------------------------|
| `.claude/skills/acquisition-system-setup/SKILL.md`              | Add system to supported systems table |
| `.claude/skills/acquisition-system-setup/<SYSTEM>_REFERENCE.md` | CREATE: Parameter documentation       |

### SKILL.md Modifications

Add the new system to the "Supported Acquisition Systems" table in SKILL.md:

```markdown
| System       | Description              | Reference                                          |
|--------------|--------------------------|----------------------------------------------------|
| `mesoscope`  | Two-photon mesoscope     | [MESOSCOPE_REFERENCE.md](MESOSCOPE_REFERENCE.md)   |
| `<new_name>` | <System description>     | [<NEW_NAME>_REFERENCE.md](<NEW_NAME>_REFERENCE.md) |
```

### Creating System Reference File

Create `<SYSTEM_NAME>_REFERENCE.md` documenting all configuration parameters. Follow the structure of
`MESOSCOPE_REFERENCE.md`:

1. **Header**: System name and brief description
2. **Filesystem Configuration**: Storage path parameters (always required)
3. **Section for each hardware category** the system uses
4. **Configuration Priority Summary**: Must-configure, should-verify, can-use-defaults

Each parameter should document: Type, Default, Valid range, Used by, Discovery tool, What it controls, Constraints.

---

## Verification Checklists

### Phase 1 Checklist (sl-shared-assets)

```
- [ ] Created <system>_configuration.py with all dataclasses
- [ ] [System]FileSystem includes root_directory, server_directory, nas_directory
- [ ] [System]SystemConfiguration inherits from YamlConfig
- [ ] [System]ExperimentConfiguration defined with trial_structures and experiment_states
- [ ] Added system to AcquisitionSystems enum
- [ ] Modified SystemConfiguration type alias
- [ ] Modified ExperimentConfiguration type alias
- [ ] Added to _SYSTEM_CONFIG_CLASSES dictionary
- [ ] Created _create_<system>_experiment_config() factory
- [ ] Added to _EXPERIMENT_CONFIG_FACTORIES dictionary
- [ ] Created system-specific descriptor classes in runtime_data.py
- [ ] Exported from configuration/__init__.py
- [ ] Exported from data_classes/__init__.py
- [ ] Exported from top-level __init__.py
- [ ] Bumped version in pyproject.toml
- [ ] All type annotations complete (MyPy strict)
- [ ] Google-style docstrings on all public APIs
```

### Phase 2 Checklist (sl-experiment)

```
- [ ] Created system package with required modules
- [ ] Implemented system-specific logic functions in data_acquisition.py
- [ ] Implemented binding classes if hardware requires lifecycle management
- [ ] Implemented data_preprocessing.py with preprocess and purge functions
- [ ] Created tools.py with get_system_configuration() function
- [ ] Added imports to execute.py for logic functions
- [ ] Added CLI commands to execute.py
- [ ] Added imports and commands to get.py (if discovery needed)
- [ ] Added imports and commands to manage.py
- [ ] Added MCP tools to mcp_servers.py (if needed)
- [ ] Added ModuleInterface classes if new microcontroller modules
- [ ] Exported new interfaces from shared_components/__init__.py
- [ ] Updated sl-shared-assets dependency version in pyproject.toml
- [ ] All type annotations complete (MyPy strict)
- [ ] Google-style docstrings on all public APIs
```

### Phase 3 Checklist (Skills)

```
- [ ] Added system to SKILL.md supported systems table
- [ ] Created <SYSTEM>_REFERENCE.md with all parameters documented
- [ ] Reference file documents filesystem, hardware, and calibration parameters
- [ ] Configuration priority summary included
```

---

## Reference Files

| File                                                   | Content                                      |
|--------------------------------------------------------|----------------------------------------------|
| [SL_SHARED_ASSETS_GUIDE.md](SL_SHARED_ASSETS_GUIDE.md) | Detailed sl-shared-assets modification guide |
| [SL_EXPERIMENT_GUIDE.md](SL_EXPERIMENT_GUIDE.md)       | Detailed sl-experiment modification guide    |

### Existing Implementation Examples

| File                                                              | Purpose                       |
|-------------------------------------------------------------------|-------------------------------|
| `../sl-shared-assets/.../mesoscope_configuration.py`              | Configuration class patterns  |
| `../sl-shared-assets/.../configuration_utilities.py`              | Registry pattern              |
| `../sl-shared-assets/.../runtime_data.py`                         | Descriptor class patterns     |
| `src/sl_experiment/mesoscope_vr/binding_classes.py`               | Binding class patterns        |
| `src/sl_experiment/mesoscope_vr/data_acquisition.py`              | Logic function patterns       |
| `src/sl_experiment/mesoscope_vr/data_preprocessing.py`            | Preprocessing patterns        |
| `src/sl_experiment/command_line_interfaces/execute.py`            | CLI command patterns          |
| `.claude/skills/acquisition-system-setup/MESOSCOPE_REFERENCE.md`  | Skill reference file example  |
