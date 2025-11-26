"""This package provides the Command Line Interfaces (CLIs) for interfacing with all user-facing library components,
exposed by installing the library into a Python environment.
"""

# Suppresses all DeprecationWarnings during production runtimes. This filter must be applied here, before any other
# imports, to ensure it takes effect before dependencies emit warnings during their import phase.
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
