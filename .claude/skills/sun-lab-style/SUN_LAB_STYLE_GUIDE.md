# Sun Lab Python Style Guide

This guide defines the documentation and coding conventions used across Sun Lab Python projects. Reference this during development to maintain consistency across all codebases.

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

### Section Guidelines

**Summary line**: Imperative mood ("Computes..." not "This function computes..."), no period unless multi-sentence.

**Notes**: Use for algorithms, references, implementation rationale. Not for parameter details.

**Args**: One line per parameter. Don't repeat type info. Start with lowercase, no period.

**Args (boolean)**: Use "Determines whether..." not "Whether..." for boolean parameters.

**Returns**: Describe what is returned, not the type. Start with uppercase if a sentence. For complex returns (tuples, dicts), describe each element in prose form.

**Raises**: Only include if the function explicitly raises exceptions.

**Attributes**: Document all instance attributes, including private ones prefixed with `_`.

**Lists**: Do not use lists (numbered or bulleted) in docstrings. Write information in prose form instead.

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

### Property Docstrings

```python
@property
def field_shape(self) -> tuple[int, int]:
    """Returns the shape of the data field as (height, width)."""
    return self._field_shape
```

### Module Docstrings

Use the format "This module provides the assets for X." to describe what the module contains:

```python
"""This module provides the assets for processing and analyzing neural imaging data."""
```

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

- Always specify dtype explicitly: `NDArray[np.float32]`, `NDArray[np.uint16]`, `NDArray[np.bool_]`, etc.
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

- Explain **why**, not **what**
- Place above the code, not at end of line (unless very short)
- Use for non-obvious logic only

```python
# The constant 2.046392675 is the theoretical injectivity bound for 2D cubic B-splines.
# Values exceeding 1/K of the grid spacing can cause non-injective (folded) transformations.
limit = (1.0 / 2.046392675) * self._grid_sampling * factor
```

### What to Avoid

- Don't add comments restating what the code does
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
