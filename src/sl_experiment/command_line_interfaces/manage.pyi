from pathlib import Path

from _typeshed import Incomplete

from .mcp_servers import run_manage_server as run_manage_server
from ..mesoscope_vr import (
    purge_session as purge_session,
    preprocess_session_data as preprocess_session_data,
    migrate_animal_between_projects as migrate_animal_between_projects,
)

CONTEXT_SETTINGS: Incomplete

def manage() -> None: ...
def preprocess_session(session_path: Path) -> None: ...
def delete_session(session_path: Path) -> None: ...
def migrate_animal(source: str, destination: str, animal: str) -> None: ...
def start_manage_mcp_server(transport: str) -> None: ...
