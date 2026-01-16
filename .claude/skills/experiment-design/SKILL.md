---
name: designing-experiments
description: >-
  Interactive guidance for building Sun lab experiment configurations using MCP tools. Covers cue
  and segment design, trial structure configuration, and experiment state definition. Use when creating
  new experiments, modifying experiment configurations, setting up trial parameters, or when the user
  asks about experiment design, templates, or MCP configuration tools.
---

# Experiment Design Skill

Provides guidance for interactively building Sun lab experiment configurations using the MCP tools exposed by this
library. Use this skill when helping users design new experiments or modify existing ones.

---

## MCP Server

Start the mesoscope MCP server with: `sl-configure mcp`

For experiment design, use the mesoscope-prefixed tools (e.g., `mesoscope_create_project_tool`). Base tools like
`list_available_templates_tool` are shared across all acquisition systems.

---

## Workflow Checklist

Copy this checklist and track your progress when creating a new experiment:

```
Experiment Creation Progress:
- [ ] Step 1: Verify templates directory is configured
- [ ] Step 2: List and select appropriate template
- [ ] Step 3: Review template details (cues, segments, trials)
- [ ] Step 4: Create project structure
- [ ] Step 5: Create experiment from template
- [ ] Step 6: Add baseline state (if needed)
- [ ] Step 7: Add experiment state with trial parameters
- [ ] Step 8: Add cooldown state (if needed)
- [ ] Step 9: Customize trial parameters (if needed)
- [ ] Step 10: Validate final configuration
```

---

## Template-Based Workflow

Experiment configurations are created from task templates stored in the sl-unity-tasks project. Templates define
the VR structure (cues, segments, trial zones) which cannot be modified after creation. Only experiment-specific
parameters can be customized.

### What Comes From Templates (Read-Only)

- Cues (visual patterns and their lengths)
- Segments (cue sequences)
- VR environment settings (corridor spacing, depth)
- Trial zone positions (trigger zones, stimulus locations)

### What Can Be Customized

- Experiment states (phases like baseline, experiment, cooldown)
- Water reward parameters (reward size, tone duration)
- Gas puff parameters (puff duration, occupancy duration)

---

## Interactive Design Workflow

### 1. Prerequisites

Ensure the templates directory is configured:
```
sl-configure templates -d /path/to/sl-unity-tasks/Assets/InfiniteCorridorTask/Configurations/Templates
```

Or via MCP:
- `set_task_templates_directory_tool(directory="/path/to/templates")`

### 2. Select a Template

List available templates:
- `list_available_templates_tool()`

Get template details:
- `get_template_info_tool(template_name="MF_Reward")`

Guide the user to select a template based on:
- Visual cue patterns needed
- Number and type of trials (lick/water reward vs occupancy/gas puff)
- Segment structure and cue sequences

### 3. Create Experiment From Template

Create the experiment configuration:
- `mesoscope_create_experiment_from_template_tool(project, experiment, template_name, ...)`

This creates a configuration with:
- All VR structure from the template
- Default trial parameters (can be customized later)
- Empty experiment states (must be added)

### 4. Add Experiment States

Common state patterns:
- **baseline**: No trials, imaging only (600s typical)
- **experiment**: Active trials with rewards/punishments (3000s typical)
- **cooldown**: No trials, post-experiment imaging (600s typical)

For each state, configure:
- State duration in seconds
- Whether trials are active
- Guidance parameters for both trial types

Use `mesoscope_add_experiment_state_tool()` for each state.

### 5. Customize Trial Parameters (Optional)

If default trial parameters need adjustment:
- `mesoscope_update_water_reward_trial_tool(project, experiment, trial_name, reward_size_ul=..., ...)`
- `mesoscope_update_gas_puff_trial_tool(project, experiment, trial_name, puff_duration_ms=..., ...)`

### 6. Validate Configuration

Always validate the final configuration:
- `mesoscope_validate_experiment_configuration_tool(project, experiment)`

---

## MCP Tools Reference

### Template Discovery Tools

| Tool                            | Description                                      |
|---------------------------------|--------------------------------------------------|
| `list_available_templates_tool` | Lists templates in configured directory          |
| `get_template_info_tool`        | Shows template details (cues, segments, trials)  |

### Setup Tools (Base Server)

| Tool                                | Description                       |
|-------------------------------------|-----------------------------------|
| `set_working_directory_tool`        | Sets the local working directory  |
| `set_task_templates_directory_tool` | Sets the templates directory path |

### Setup Tools (Mesoscope Server)

| Tool                                          | Description                    |
|-----------------------------------------------|--------------------------------|
| `mesoscope_create_project_tool`               | Creates a new project          |
| `mesoscope_create_experiment_from_template_tool` | Creates experiment from template |

### Trial Parameter Tools (Mesoscope Server)

| Tool                                    | Description                           |
|-----------------------------------------|---------------------------------------|
| `mesoscope_update_water_reward_trial_tool` | Updates reward size and tone duration |
| `mesoscope_update_gas_puff_trial_tool`     | Updates puff and occupancy durations  |

### Experiment State Tools (Mesoscope Server)

| Tool                                   | Description                |
|----------------------------------------|----------------------------|
| `mesoscope_add_experiment_state_tool`    | Adds an experiment state   |
| `mesoscope_update_experiment_state_tool` | Modifies an existing state |
| `mesoscope_remove_experiment_state_tool` | Removes a state            |

### Query Tools (Mesoscope Server)

| Tool                                             | Description               |
|--------------------------------------------------|---------------------------|
| `mesoscope_read_experiment_configuration_tool`     | Reads full config summary |
| `mesoscope_list_experiment_cues_tool`              | Lists all defined cues    |
| `mesoscope_list_experiment_segments_tool`          | Lists all segments        |
| `mesoscope_list_experiment_trials_tool`            | Lists all trial structures |
| `mesoscope_list_experiment_states_tool`            | Lists all states          |
| `mesoscope_validate_experiment_configuration_tool` | Validates completeness    |

---

## Example Session

```
User: I need to create an experiment for the MF_Reward task

Agent: Let me check the available templates and create the experiment.

1. list_available_templates_tool()
   -> Shows MF_Reward, MF_Aversion_Reward, SSO_*, etc.

2. get_template_info_tool(template_name="MF_Reward")
   -> Shows cues, segments, and trial structures

3. mesoscope_create_project_tool(project="my_project")
   -> Creates project directory

4. mesoscope_create_experiment_from_template_tool(
       project="my_project",
       experiment="session_1",
       template_name="MF_Reward",
       default_reward_size_ul=5.0
   )
   -> Creates experiment with 8 water reward trials

5. mesoscope_add_experiment_state_tool(
       project="my_project",
       experiment="session_1",
       name="baseline",
       experiment_state_code=1,
       system_state_code=1,
       state_duration_s=600,
       supports_trials=False
   )

6. mesoscope_add_experiment_state_tool(
       project="my_project",
       experiment="session_1",
       name="experiment",
       experiment_state_code=2,
       system_state_code=2,
       state_duration_s=3000,
       supports_trials=True,
       reinforcing_initial_guided_trials=3,
       reinforcing_recovery_failed_threshold=6,
       reinforcing_recovery_guided_trials=3
   )

7. mesoscope_validate_experiment_configuration_tool(project="my_project", experiment="session_1")
   -> Confirms configuration is valid
```

---

## Best Practices

1. **Always use templates**: VR structure must come from pre-defined templates
2. **Review template before use**: Use `get_template_info_tool` to understand what trials are included
3. **Add all required states**: Experiment needs at least one state to be valid
4. **Validate after changes**: Use `mesoscope_validate_experiment_configuration_tool` after modifications
5. **Ask clarifying questions**: When in doubt, ask the user about their experimental design

---

## Available Templates

Templates are stored in sl-unity-tasks at:
`Assets/InfiniteCorridorTask/Configurations/Templates/`

Common templates include:
- `MF_Reward` - Cyclic 8-cue reward task
- `MF_Aversion_Reward` - Combined aversion/reward task
- `SSO_*` - Various sequence learning tasks

Use `list_available_templates_tool()` to see all available templates.
