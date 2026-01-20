# Claude Code Instructions

## Session Start Behavior

At the beginning of each coding session, before making any code changes, you should build a comprehensive
understanding of the codebase by invoking the `/explore-codebase` skill.

This ensures you:
- Understand the project architecture before modifying code
- Follow existing patterns and conventions
- Don't introduce inconsistencies or break integrations

## Code Contributions and Review

Before writing, modifying, or reviewing any code, you MUST invoke the `/sun-lab-style` skill to load the Sun Lab
coding conventions. All code contributions must strictly follow these conventions and all code reviews must check for
compliance. The style guide covers:
- Python code (docstrings, type annotations, naming, error handling)
- README files (structure, voice, tense)
- Git commit messages (format, verb tense, punctuation)
- Claude skill files (frontmatter, formatting, voice)

## Cross-Referenced Library Verification

Sun Lab projects often depend on other `ataraxis-*` or `sl-*` libraries. These libraries may be stored locally in the
same parent directory as this project (`/home/cyberaxolotl/Desktop/GitHubRepos/`).

**Before writing code that interacts with a cross-referenced library, you MUST:**

1. **Check for local version**: Look for the library in the parent directory (e.g., `../ataraxis-video-system/`,
   `../sl-shared-assets/`).

2. **Compare versions**: If a local copy exists, compare its version against the latest release or main branch on
   GitHub:
   - Read the local `pyproject.toml` to get the current version
   - Use `gh api repos/Sun-Lab-NBB/{repo-name}/releases/latest` to check the latest release
   - Alternatively, check the main branch version on GitHub

3. **Handle version mismatches**: If the local version differs from the latest release or main branch, notify the user
   with the following options:
   - **Use online version**: Fetch documentation and API details from the GitHub repository
   - **Update local copy**: The user will pull the latest changes locally before proceeding

4. **Proceed with correct source**: Use whichever version the user selects as the authoritative reference for API
   usage, patterns, and documentation.

**Why this matters**: Skills and documentation may reference outdated APIs. Always verify against the actual library
state to prevent integration errors.

## Available Skills

| Skill                       | Description                                                                  |
|-----------------------------|------------------------------------------------------------------------------|
| `/explore-codebase`         | Perform in-depth codebase exploration at session start                       |
| `/sun-lab-style`            | Apply Sun Lab coding conventions (REQUIRED for all code changes)             |
| `/camera-interface`         | Guide for using ataraxis-video-system to implement camera functionality      |
| `/acquisition-system-setup` | Configure data acquisition systems (uses MCP tools from sl-shared-assets)    |
| `/experiment-design`        | Interactive guidance for building experiment configurations (uses MCP tools) |

## Project Context

This is **sl-experiment**, a Python library for scientific data acquisition in the Sun Lab at Cornell University. The
library is designed to manage any combination of acquisition systems and can be extended to support new systems or
modified to remove existing ones. Currently, sl-experiment manages the **Mesoscope-VR** two-photon imaging system,
which combines brain imaging with virtual reality behavioral tasks.

### Key Areas

| Directory                                    | Purpose                                                  |
|----------------------------------------------|----------------------------------------------------------|
| `src/sl_experiment/command_line_interfaces/` | CLI entry points (sl-get, sl-manage, sl-run)             |
| `src/sl_experiment/mesoscope_vr/`            | Mesoscope-VR system implementation (current system)      |
| `src/sl_experiment/shared_components/`       | Cross-system utilities shared by all acquisition systems |

### Architecture

- Three CLI commands delegate to specialized subsystems
- Hardware abstraction via binding classes (Zaber motors, cameras, microcontrollers)
- Shared memory IPC for GUI-runtime communication
- Session-based data management with distributed storage

### Code Standards

- MyPy strict mode with full type annotations
- Google-style docstrings
- 120 character line limit
- See `/sun-lab-style` for complete conventions

### Workflow Guidance

**Adding a new acquisition system:**

1. Create a new package under `src/sl_experiment/` (e.g., `src/sl_experiment/new_system/`)
2. Follow the `mesoscope_vr` structure:
   - `__init__.py` - Export logic functions (e.g., `experiment_logic`, `maintenance_logic`)
   - `binding_classes.py` - Hardware wrapper classes managing device lifecycles
   - `data_acquisition.py` - Runtime logic for sessions
   - `data_preprocessing.py` - Post-session data processing
   - Additional modules as needed (UI, tools, visualizers)
3. Define system configuration in `sl-shared-assets` before implementation (see below)
4. Update CLI modules in `command_line_interfaces/` to include new system commands

**Adding hardware bindings:**

1. For shared hardware (microcontrollers), add `ModuleInterface` subclasses to `shared_components/module_interfaces.py`
2. For system-specific hardware, add wrapper classes to the system's `binding_classes.py`
3. Follow existing patterns: wrapper classes that manage device lifecycle (`connect()`, `start()`, `stop()`)
4. Use configuration dataclasses from `sl-shared-assets` for hardware parameters

**Modifying CLI commands:**

1. Identify the appropriate CLI module: `execute.py` (sl-run), `manage.py` (sl-manage), or `get.py` (sl-get)
2. Add Click-decorated command functions following existing patterns
3. Import logic functions from the relevant acquisition system package
4. Register commands with the appropriate Click group

**Modifying sl-shared-assets (configuration dataclasses):**

Changes to system configuration require updates in `sl-shared-assets` (`../sl-shared-assets/`):

1. For new acquisition systems, create a configuration module in `src/sl_shared_assets/configuration/`
   - Define system-specific dataclasses (cameras, microcontrollers, external assets, filesystem paths)
   - Follow `mesoscope_configuration.py` as a reference for structure and patterns
   - Add exports to `configuration/__init__.py` and the top-level `__init__.py`
2. For experiment configuration changes, modify `experiment_configuration.py` (trial types, states)
3. For VR environment changes, modify `vr_configuration.py` (cues, segments, environments)
4. For new runtime/session data structures, add dataclasses to `data_classes/`
5. Update MCP tools in `interfaces/mcp_server.py` if configuration needs programmatic access
6. Bump the `sl-shared-assets` version and update the dependency in sl-experiment's `pyproject.toml`

**Modifying sl-micro-controllers (hardware modules):**

Changes to microcontroller firmware require updates in `sl-micro-controllers` (`../sl-micro-controllers/`):

1. For new hardware modules, create a header file in `src/` (e.g., `new_module.h`)
   - Follow existing module patterns (e.g., `valve_module.h`, `encoder_module.h`)
   - Define module type code, command codes, and data codes
   - Implement the module class with required command handlers
2. Register the module in `main.cpp` under the appropriate microcontroller type (ACTOR, SENSOR, or ENCODER)
3. Create corresponding `ModuleInterface` subclass in sl-experiment's `shared_components/module_interfaces.py`
   - Match type codes, command codes, and data codes with the firmware
4. Upload updated firmware to microcontrollers using PlatformIO
5. Document hardware assembly requirements if new physical components are needed
