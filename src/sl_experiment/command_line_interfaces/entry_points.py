"""This module provides the entry point wrapper functions for all CLI commands.

The warning filter is applied at module level before any other imports to ensure deprecation warnings from dependencies
are suppressed during the import phase.
"""

import warnings as wa

wa.warn_explicit = wa.warn = lambda *_, **__: None


def get_cli() -> None:
    """Entry point for the 'sl-get' CLI command."""
    from ..command_line_interfaces.get import get  # noqa: PLC0415

    get()


def manage_cli() -> None:
    """Entry point for the 'sl-manage' CLI command."""
    from ..command_line_interfaces.manage import manage  # noqa: PLC0415

    manage()


def run_cli() -> None:
    """Entry point for the 'sl-run' CLI command."""
    from ..command_line_interfaces.execute import run  # noqa: PLC0415

    run()
