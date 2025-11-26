"""This module provides the entry point wrapper functions for all CLI commands.

The warning filter is applied at module level before any other imports to ensure deprecation warnings from dependencies
are suppressed during the import phase.
"""

import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)


def get_cli() -> None:
    """Entry point for the 'sl-get' CLI command."""
    from sl_experiment.command_line_interfaces.get import get

    get()


def manage_cli() -> None:
    """Entry point for the 'sl-manage' CLI command."""
    from sl_experiment.command_line_interfaces.manage import manage

    manage()


def run_cli() -> None:
    """Entry point for the 'sl-run' CLI command."""
    from sl_experiment.command_line_interfaces.execute import run

    run()
