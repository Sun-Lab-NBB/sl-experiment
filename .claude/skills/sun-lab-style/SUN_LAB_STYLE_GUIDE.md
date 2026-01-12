# Sun Lab Python Style Guide

This guide defines the documentation and coding conventions used across Sun Lab Python projects.
Reference this during development to maintain consistency across all codebases.

---

## Docstrings

Use **Google-style docstrings** with the following sections (in order):

```python
def function_name(param1: int, param2: str = "default") -> bool:
    """Brief one-line summary of what the function does.

    Notes:
        Additional context, background, or implementation details. Use this for
        explaining algorithms, referencing papers, or clarifying non-obvious behavior.
        Multi-sentence explanations go here.

    Args:
        param1: Description without repeating the type (types are in signature).
        param2: Description of parameter with default value behavior if relevant.

    Returns:
        Description of return value. For simple returns, one line is sufficient.
        For complex returns (tuples, dicts), describe each element.

    Raises:
        ValueError: When this error occurs and why.
        TypeError: When this error occurs and why.
    """
```

### General Rules

**Punctuation**: Always use proper punctuation in all documentation: docstrings, comments, and
argument descriptions.

### Section Guidelines

**Summary line**: Use imperative mood for ALL docstrings (functions, methods, classes, modules).
Use verbs like "Computes...", "Defines...", "Configures...", "Processes..." rather than noun
phrases like "A class that..." or "Configuration for...".

**Extended description**: Only include if the summary line is not sufficient to fully understand
what the function does. Use third person ("This method creates..."). Do not explain every step of
implementation; focus on the high-level purpose.

**Notes**: Use for usage guidance, non-obvious behavior, algorithms, references, and implementation
rationale. This section explains how the function is used or unique things to know about it, not
what it does.

**Args**: Don't repeat type info. Start with uppercase after the colon. Always use proper
punctuation. Descriptions must be clear enough to give the user a good understanding of what the
argument controls or does.

**Args (boolean)**: Use "Determines whether..." not "Whether..." for boolean parameters.

**Args (enum)**: Type hint should accept both the enum and its base type (e.g.,
`VisualizerMode | int` for IntEnum). Include "Must be a valid X enumeration member." at the end
of the description.

**Returns**: Describe what is returned, not the type. Start with uppercase if a sentence. For
complex returns (tuples, dicts), describe each element in prose form.

**Raises**: Only include if the function explicitly raises exceptions.

**Attributes**: Document all instance attributes, including private ones prefixed with `_`.

**Lists**: Do not use lists (numbered or bulleted) in docstrings. Write information in prose form
instead.

### Class Docstrings with Attributes

For classes, include an Attributes section listing all instance attributes:

```python
class DataProcessor:
    """Processes experimental data for analysis.

    Args:
        data_path: Path to the input data file.
        sampling_rate: The sampling rate in Hz.
        enable_filtering: Determines whether to apply bandpass filtering.

    Attributes:
        _data_path: Cached path to input data.
        _sampling_rate: Cached sampling rate parameter.
        _enable_filtering: Cached filtering flag.
        _processed_data: Dictionary storing processed results.
    """
```

### Enum and Dataclass Attributes

For enums and dataclasses, document each attribute inline using triple-quoted strings:

```python
class VisualizerMode(IntEnum):
    """Defines the display modes for the BehaviorVisualizer."""

    LICK_TRAINING = 0
    """Displays only lick sensor and valve plots."""
    RUN_TRAINING = 1
    """Displays lick, valve, and running speed plots."""
    EXPERIMENT = 2
    """Displays all plots including the trial performance panel."""


@dataclass
class SessionConfig:
    """Defines the configuration parameters for an experiment session."""

    animal_id: str
    """The unique identifier for the animal."""
    session_duration: float
    """The duration of the session in seconds."""
```

### Property Docstrings

```python
@property
def field_shape(self) -> tuple[int, int]:
    """Returns the shape of the data field as (height, width)."""
    return self._field_shape
```

### Module Docstrings

Follow the same imperative mood pattern as other docstrings:

```python
"""Provides assets for processing and analyzing neural imaging data."""
```

### CLI Command Docstrings

CLI commands and command groups use a specialized docstring format because Click parses these
docstrings into help messages displayed to users. Do not use standard docstring sections (Notes,
Args, Returns, Raises) as they will appear verbatim in the CLI help output.

```python
@click.command()
def process_data(input_path: Path, output_path: Path) -> None:
    """Processes raw experimental data and saves the results.

    This command reads data from the input path, applies standard preprocessing
    steps, and writes the processed output to the specified location. The input
    must be a valid .feather file containing session data.
    """
```

The first sentence serves as the short command description shown in command listings. The
remaining prose provides additional context shown in the detailed help for that specific command.

---

## Type Annotations

### General Rules

- All function parameters and return types must have annotations
- Use `-> None` for functions that don't return a value
- Use `| None` for optional types (not `Optional[T]`)
- Use lowercase `tuple`, `list`, `dict` (not `Tuple`, `List`, `Dict`)
- Avoid `any` type; use explicit union types instead

### NumPy Arrays

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from numpy.typing import NDArray

def process(data: NDArray[np.float32]) -> NDArray[np.float32]:
    ...
```

- Always specify dtype explicitly: `NDArray[np.float32]`, `NDArray[np.uint16]`,
  `NDArray[np.bool_]`, etc.
- Never use unparameterized `NDArray`
- Use `TYPE_CHECKING` block for `NDArray` to avoid runtime import overhead

### Class Attributes

```python
def __init__(self, height: int, width: int) -> None:
    self._field_shape: tuple[int, int] = (height, width)
    self._data: tuple[NDArray[np.float32], NDArray[np.float32]] = (
        np.zeros(self._shape, dtype=np.float32),
        np.zeros(self._shape, dtype=np.float32),
    )
```

---

## Naming Conventions

### Variables

Use **full words**, not abbreviations:

| Avoid | Prefer |
|-------|--------|
| `t`, `t_sq` | `interpolation_factor`, `t_squared` |
| `coeff`, `coeffs` | `coefficient`, `coefficients` |
| `pos`, `idx` | `position`, `index` |
| `img`, `val` | `image`, `value` |
| `num`, `dnum` | `numerator`, `denominator` |
| `gy`, `gx` | `grid_index_y`, `grid_index_x` |

### Functions

- Use descriptive verb phrases: `compute_coefficients`, `extract_features`
- Private functions start with underscore: `_process_batch`, `_validate_input`
- Avoid generic names like `process`, `handle`, `do_something`

### Constants

Module-level constants with type annotations and descriptive names:

```python
# Minimum number of samples required for statistical validity.
_MINIMUM_SAMPLE_COUNT: int = 100
```

---

## Function Calls

**Always use keyword arguments** for clarity:

```python
# Good
np.zeros((4,), dtype=np.float32)
np.empty((4,), dtype=np.float32)
compute_coefficients(interpolation_factor=t, output=result)
self._get_data(dimension=0)

# Avoid
np.zeros((4,), np.float32)
compute_coefficients(t, result)
self._get_data(0)
```

Exception: Single positional arguments for obvious cases like `range(4)`, `len(array)`.

---

## Error Handling

Use `console.error` from `ataraxis_base_utilities`:

```python
from ataraxis_base_utilities import console

def process_data(self, data: NDArray[np.float32], threshold: float) -> None:
    if not (0 < threshold <= 1):
        message = (
            f"Unable to process data with the given threshold. The threshold must be in range "
            f"(0, 1], but got {threshold}."
        )
        console.error(message=message, error=ValueError)
```

### Error Message Format

- Start with context: "Unable to [action] using [input]."
- Explain the constraint: "The [parameter] must be [constraint]"
- Show actual value: "but got {value}."
- Use f-strings for interpolation

---

## Numba Functions

### Decorator Patterns

```python
# Standard cached function
@numba.njit(cache=True)
def _compute_values(...) -> None:
    ...

# Parallelized function
@numba.njit(cache=True, parallel=True)
def _process_batch(...) -> None:
    for i in prange(data.shape[0]):  # Parallel outer loop
        for j in range(data.shape[1]):  # Sequential inner loop
            ...

# Inlined helper (for small, frequently-called functions)
@numba.njit(cache=True, inline="always")
def compute_coefficients(...) -> None:
    ...
```

### Guidelines

- Always use `cache=True` for disk caching (avoids recompilation)
- Use `parallel=True` with `prange` only when no race conditions exist
- Use `inline="always"` for small helper functions called in hot loops
- Don't use `nogil` unless explicitly using threading
- Use Python type hints (not Numba signature strings) for readability

### Variable Allocation in Parallel Loops

```python
for i in prange(data.shape[0]):
    # Allocate per-thread arrays INSIDE the parallel loop
    temp_y = np.empty((4,), dtype=np.float32)
    temp_x = np.empty((4,), dtype=np.float32)

    for j in range(data.shape[1]):
        ...
```

---

## Comments

### Inline Comments

- Use third person imperative ("Configures..." not "This section configures..." or "Configure...")
- Place above the code, not at end of line (unless very short)
- Use comments to explain non-obvious logic or provide context that aids understanding
- When explaining what code does, focus on the high-level purpose, not obvious implementation
  details

```python
# The constant 2.046392675 is the theoretical injectivity bound for 2D cubic B-splines.
# Values exceeding 1/K of the grid spacing can cause non-injective (folded) transformations.
limit = (1.0 / 2.046392675) * self._grid_sampling * factor

# Configures the speed axis, which only exists in RUN_TRAINING and experiment modes.
if self._speed_axis is not None:
    ...

# Creates the reinforcing trial rectangles in the bottom row.
for i in range(20):
    ...
```

### What to Avoid

- Don't reiterate the obvious (e.g., `# Set x to 5` before `x = 5`)
- Don't add docstrings/comments to code you didn't write or modify
- Don't add type annotations as comments (use actual type hints)

---

## Imports

### Organization

```python
"""Module docstring."""

from typing import TYPE_CHECKING

import numba
from numba import prange
import numpy as np
from ataraxis_base_utilities import console

if TYPE_CHECKING:
    from numpy.typing import NDArray
```

Order:
1. Future imports (if any)
2. Standard library
3. `TYPE_CHECKING` import from typing
4. Third-party imports (alphabetical)
5. Local imports
6. `if TYPE_CHECKING:` block for type-only imports

---

## Class Design

### Constructor Parameters

Use explicit parameters instead of tuples/dicts:

```python
# Good
def __init__(self, field_height: int, field_width: int, sampling: float) -> None:
    self._field_shape: tuple[int, int] = (field_height, field_width)

# Avoid
def __init__(self, field_shape: tuple[int, int], sampling: float) -> None:
    self._field_shape = field_shape
```

### Properties vs Methods

- Use `@property` for simple attribute access that may involve computation
- Use methods for operations that clearly "do something" or take parameters

```python
@property
def data_shape(self) -> tuple[int, int]:
    """Returns the shape of the data as (height, width)."""
    ...

def set_from_array(self, data: NDArray[np.float32], weights: NDArray[np.float32]) -> None:
    """Sets internal state from the provided arrays."""
    ...
```

### Method Types

Use the appropriate method decorator based on what the method accesses:

- **Instance methods** (no decorator): Use when the method accesses instance attributes (`self`).
- **`@staticmethod`**: Use when the method doesn't access instance or class attributes. Prefer
  this over instance methods when `self` is not needed.
- **`@classmethod`**: Use when the method needs access to class attributes but not instance
  attributes.

```python
class DataProcessor:
    _default_threshold: float = 0.5  # Class attribute.

    def process(self, data: NDArray[np.float32]) -> NDArray[np.float32]:
        """Processes data using instance configuration."""
        return data * self._scale_factor  # Uses self.

    @staticmethod
    def validate_input(data: NDArray[np.float32]) -> bool:
        """Validates input data format."""
        return data.ndim == 2  # No self or cls needed.

    @classmethod
    def from_config(cls, config: dict) -> "DataProcessor":
        """Creates an instance from a configuration dictionary."""
        return cls(threshold=config.get("threshold", cls._default_threshold))
```

### Visibility (Public vs Private)

- **Private** (`_` prefix): Use for anything internal to the class/module that should not be
  accessed externally. This includes helper methods, internal attributes, and implementation
  details.
- **Public** (no prefix): Use only for methods, functions, and classes that are intended to be
  used from other modules or by external code.

```python
class SessionManager:
    def __init__(self) -> None:
        self._session_id: str = ""  # Private attribute.
        self._is_active: bool = False  # Private attribute.

    def start_session(self) -> None:
        """Starts a new session."""  # Public - called externally.
        self._initialize_resources()
        self._is_active = True

    def _initialize_resources(self) -> None:
        """Initializes internal resources."""  # Private - internal helper.
        ...
```

---

## Line Length and Formatting

- Maximum line length: 120 characters
- Break long function calls across multiple lines:

```python
result = compute_transformation(
    input_data=self._data,
    parameters=self._get_parameters(dimension=dimension),
    weights=weights,
)
```

- Use parentheses for multi-line strings in error messages:

```python
message = (
    f"Unable to process the input data. The threshold must be in range "
    f"(0, 1], but got {threshold}."
)
```

---

## Linting and Code Quality

### Running the Linter

Run `tox -e lint` after making changes. All issues must either be resolved or marked with proper
`# noqa` ignore statements.

### Resolution Policy

Prefer resolving issues unless the resolution would:
- Make the code unnecessarily complex
- Hurt performance by adding redundant checks
- Harm codebase readability instead of helping it

### Magic Numbers (PLR2004)

For magic number warnings, prefer defining constants:

**Local constants**: Use when the value is specific to a single function or method.

```python
def calculate_threshold(self, value: float) -> float:
    """Calculates the adjusted threshold."""
    adjustment_factor = 1.5  # Empirically determined scaling factor.
    return value * adjustment_factor
```

**Module-level constants**: Use when the value is a configuration parameter that may need
adjustment later.

```python
# Maximum number of retry attempts for network operations.
_MAX_RETRY_ATTEMPTS: int = 3

# Default timeout in milliseconds for sensor polling.
_SENSOR_TIMEOUT_MS: int = 500
```

### Using noqa

When suppressing a warning, always include the specific error code:

```python
if mode == 3:  # noqa: PLR2004 - LICK_TRAINING mode value from VisualizerMode enum.
    ...
```

### Typos

- **Obvious typos**: Must be fixed immediately (e.g., "teh" → "the", "fucntion" → "function").
- **Ambiguous typos**: If a typo may be intentional (e.g., domain-specific terminology,
  abbreviations), flag it for user confirmation before changing.
