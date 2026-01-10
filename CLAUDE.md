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

## Available Skills

- `/explore-codebase` - Perform in-depth codebase exploration
- `/sun-lab-style` - Apply Sun Lab Python coding conventions (REQUIRED for all code changes)

## Project Context

This is **sl-experiment**, a Python library for scientific data acquisition in the Sun Lab at Cornell University. It manages the Mesoscope-VR two-photon imaging system combining brain imaging with virtual reality behavioral tasks.

### Key Areas

| Directory | Purpose |
|-----------|---------|
| `src/sl_experiment/command_line_interfaces/` | CLI entry points (sl-get, sl-manage, sl-run) |
| `src/sl_experiment/mesoscope_vr/` | Core system implementation |
| `src/sl_experiment/shared_components/` | Cross-system utilities |

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
