---
name: explore-codebase
description: >-
  Perform in-depth codebase exploration at the start of a coding session. Builds comprehensive
  understanding of project structure, architecture, key components, and patterns.
---

# Codebase Exploration

When this skill is invoked, perform a thorough exploration of the codebase to build deep
understanding before any coding work begins.

## Exploration Requirements

You MUST use the Task tool with `subagent_type: Explore` to investigate the following areas:

### 1. Project Overview
- Read README, pyproject.toml, setup.py, and documentation
- Understand the project's purpose, goals, and primary use cases
- Identify the target users/audience

### 2. Directory Structure
- Map the complete directory structure
- Explain what each major directory/module contains
- Identify source code vs configuration vs documentation vs tests

### 3. Architecture
- Understand the overall system architecture
- Identify main components and how they interact
- Document communication patterns (IPC, APIs, events, etc.)
- Note any external system integrations

### 4. Core Modules
- **Entry points**: Main execution flow, CLI commands, APIs
- **Business logic**: Core functionality and algorithms
- **Data models**: Classes, schemas, data structures
- **Utilities**: Helper functions, shared components
- **Configuration**: How settings are managed and loaded

### 5. Dependencies
- Review external library dependencies
- Understand how key dependencies are used
- Note version constraints or compatibility requirements

### 6. Testing Structure
- Identify testing frameworks used
- Understand test organization
- Note any test utilities or fixtures

### 7. Design Patterns & Conventions
- Document coding patterns used (factories, strategies, etc.)
- Note naming conventions
- Identify code style and formatting standards

### 8. Key Files
- List the most important files with brief descriptions
- Include file paths and line counts where relevant

## Output Format

After exploration, provide a structured summary with:
- Project purpose (1-2 sentences)
- Architecture diagram (ASCII if helpful)
- Key components table
- Important files list with paths
- Notable patterns or conventions
- Any areas of complexity or concern

## Usage

This skill should be invoked at the start of coding sessions to ensure full context before making
changes. It prevents blind modifications and ensures understanding of existing patterns.
