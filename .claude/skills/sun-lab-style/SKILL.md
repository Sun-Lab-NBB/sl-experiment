---
name: sun-lab-style
description: >-
  Apply Sun Lab Python coding conventions when writing, reviewing, or refactoring code. Covers
  docstrings, type annotations, naming conventions, error handling, Numba functions, and
  formatting standards.
---

# Sun Lab Style Guide

When writing, reviewing, or refactoring Python code, apply the conventions defined in the Sun Lab
style guide.

See @SUN_LAB_STYLE_GUIDE.md for complete guidelines.

## Key Conventions

- **Docstrings**: Google-style with Args, Returns, Raises, Notes, Attributes sections
- **Type annotations**: All parameters and returns annotated; always specify dtype for arrays
  (e.g., `NDArray[np.float32]`)
- **Naming**: Full words (not abbreviations); descriptive verb phrases for functions
- **Function calls**: Always use keyword arguments for clarity
- **Error handling**: Use `console.error()` from `ataraxis_base_utilities`
- **Numba**: Always use `cache=True`; use `parallel=True` with `prange` only when safe
- **Line length**: Maximum 120 characters
