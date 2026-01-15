# Claude Code Instructions

## Session Start Behavior

At the beginning of each coding session, before making any code changes, you should build a comprehensive understanding of the codebase by invoking the `/explore-codebase` skill.

This ensures you:
- Understand the project architecture before modifying code
- Follow existing patterns and conventions
- Don't introduce inconsistencies or break integrations

## Code Contributions and Review

Before writing, modifying, or reviewing any code, you MUST invoke the `/sun-lab-style` skill to load the Sun Lab Python coding conventions. All code contributions must strictly follow these conventions and all code reviews must check for compliance. Key conventions include:
- Google-style docstrings with proper sections
- Full type annotations with explicit array dtypes
- Keyword arguments for function calls
- Third person imperative comments
- Proper error handling with `console.error()`

## Cross-Referenced Library Verification

Sun Lab projects often depend on other `ataraxis-*` or `sl-*` libraries. These libraries may be stored
locally in the same parent directory as this project (`/home/cyberaxolotl/Desktop/GitHubRepos/`).

**Before writing code that interacts with a cross-referenced library, you MUST:**

1. **Check for local version**: Look for the library in the parent directory (e.g.,
   `../ataraxis-video-system/`, `../sl-shared-assets/`).

2. **Compare versions**: If a local copy exists, compare its version against the latest release or
   main branch on GitHub:
   - Read the local `pyproject.toml` to get the current version
   - Use `gh api repos/Sun-Lab-NBB/{repo-name}/releases/latest` to check the latest release
   - Alternatively, check the main branch version on GitHub

3. **Handle version mismatches**: If the local version differs from the latest release or main branch,
   notify the user with the following options:
   - **Use online version**: Fetch documentation and API details from the GitHub repository
   - **Update local copy**: The user will pull the latest changes locally before proceeding

4. **Proceed with correct source**: Use whichever version the user selects as the authoritative
   reference for API usage, patterns, and documentation.

**Why this matters**: Skills and documentation may reference outdated APIs. Always verify against the
actual library state to prevent integration errors.

## Available Skills

- `/explore-codebase` - Perform in-depth codebase exploration
- `/sun-lab-style` - Apply Sun Lab Python coding conventions (REQUIRED for all code changes)
- `/camera-interface` - Guide for using ataraxis-video-system to implement camera functionality
- `/acquisition-system-setup` - Configure data acquisition systems (uses MCP tools from sl-shared-assets)

## Project Context

This is **sl-experiment**, a Python library for scientific data acquisition in the Sun Lab at Cornell University. The library is designed to manage any combination of acquisition systems and can be extended to support new systems or modified to remove existing ones. Currently, sl-experiment manages the **Mesoscope-VR** two-photon imaging system, which combines brain imaging with virtual reality behavioral tasks.

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
