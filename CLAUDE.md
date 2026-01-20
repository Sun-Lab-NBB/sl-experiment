# Claude Code Instructions

## Session Start Behavior

At the beginning of each coding session, before making any code changes, you should build a comprehensive
understanding of the codebase by invoking the `/explore-codebase` skill.

This ensures you:
- Understand the project architecture before modifying code
- Follow existing patterns and conventions
- Don't introduce inconsistencies or break integrations

## Style Guide Requirements

You MUST invoke `/sun-lab-style` and read the appropriate guide before performing ANY of the following tasks:

| Task                              | Guide to Read      |
|-----------------------------------|--------------------|
| Writing or modifying Python code  | PYTHON_STYLE.md    |
| Writing or modifying README files | README_STYLE.md    |
| Writing git commit messages       | COMMIT_STYLE.md    |
| Writing or modifying skill files  | SKILL_STYLE.md     |

This is non-negotiable. The skill contains verification checklists that you MUST complete before submitting any work.
Failure to read the appropriate guide results in style violations.

## Acquisition System Configuration

When users want to interact with the acquisition system hardware or configuration, you MUST invoke the
`/acquisition-system-setup` skill. This skill provides MCP tools for hardware discovery and guides configuration file
editing.

**Invoke this skill when users want to:**
- Discover hardware (cameras, microcontrollers, Zaber motors, MQTT broker)
- Set up or configure an acquisition system
- Change system parameters (ports, calibration values, thresholds)
- Verify system configuration before running experiments
- Troubleshoot hardware connectivity or configuration issues

**Example triggers:**
- "What cameras are connected?"
- "Set up the mesoscope system"
- "Change the lick threshold"
- "Check if the MQTT broker is running"
- "Verify my system configuration"

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

| Skill                        | Description                                                                  |
|------------------------------|------------------------------------------------------------------------------|
| `/explore-codebase`          | Perform in-depth codebase exploration at session start                       |
| `/sun-lab-style`             | Apply Sun Lab coding conventions (REQUIRED for all code changes)             |
| `/camera-interface`          | Guide for using ataraxis-video-system to implement camera functionality      |
| `/acquisition-system-setup`  | Configure data acquisition systems (uses MCP tools from sl-shared-assets)    |
| `/experiment-design`         | Interactive guidance for building experiment configurations (uses MCP tools) |
| `/adding-acquisition-system` | Guide for adding support for new acquisition systems to the framework        |

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

Use the `/adding-acquisition-system` skill for comprehensive guidance. The skill covers:
1. Creating configuration dataclasses in sl-shared-assets (Phase 1)
2. Implementing runtime logic and CLI in sl-experiment (Phase 2)
3. Updating the acquisition-system-setup skill with system documentation (Phase 3)

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

Changes to system configuration require updates in `sl-shared-assets` (`../sl-shared-assets/`). See the
`/adding-acquisition-system` skill for detailed guidance on:
- Creating system-specific configuration modules
- Registering systems in the configuration utilities
- Exporting new classes at all levels

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
