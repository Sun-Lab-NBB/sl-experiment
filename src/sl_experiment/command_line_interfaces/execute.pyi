import click
from _typeshed import Incomplete

from ..mesoscope_vr import (
    experiment_logic as experiment_logic,
    maintenance_logic as maintenance_logic,
    run_training_logic as run_training_logic,
    lick_training_logic as lick_training_logic,
    window_checking_logic as window_checking_logic,
)

CONTEXT_SETTINGS: Incomplete

def run() -> None: ...
def maintain_acquisition_system() -> None: ...
@click.pass_context
def session(ctx: click.Context, user: str, project: str, animal: str, animal_weight: float) -> None: ...
@click.pass_context
def check_window(ctx: click.Context) -> None: ...
@click.pass_context
def lick_training(
    ctx: click.Context,
    maximum_time: int | None,
    minimum_delay: int | None,
    maximum_delay: int | None,
    maximum_volume: float | None,
    unconsumed_rewards: int | None,
) -> None: ...
@click.pass_context
def run_training(
    ctx: click.Context,
    maximum_time: int | None,
    initial_speed: float | None,
    initial_duration: float | None,
    increase_threshold: float | None,
    speed_step: float | None,
    duration_step: float | None,
    maximum_volume: float | None,
    maximum_idle_time: float | None,
    unconsumed_rewards: int | None,
) -> None: ...
@click.pass_context
def run_experiment(ctx: click.Context, experiment: str, unconsumed_rewards: int | None) -> None: ...
