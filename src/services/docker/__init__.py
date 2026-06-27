"""Docker service layer — Phase 3 implements the real EngineClient."""

from src.services.docker.compose_runner import (
    BoundComposeRunner,
    ComposePsRow,
    ComposeRunner,
    DefaultSpawner,
    Spawner,
    default_spawner,
)
from src.services.docker.engine_client import create_engine_client
from src.services.docker.git_guard import (
    GitRunner,
    GitStatusReport,
    RealGitRunner,
    check_env_file_git_status,
)
from src.services.docker.image_reference import (
    ImageReference,
    parse_image_reference,
)
from src.services.docker.image_validator import (
    ImageValidationResult,
    ImageValidator,
    create_image_validator,
    format_image_validation_error,
    image_validation_warnings,
)
from src.services.docker.registry_client import (
    RegistryCheckResult,
    RegistryCheckStatus,
    RegistryCheckStatusValues,
    RegistryClient,
    create_registry_client,
)
from src.services.docker.types import (
    ContainerInspect,
    ContainerStats,
    ContainerSummary,
    EngineClient,
    ImageInspect,
    ImageSummary,
)

__all__ = [
    "BoundComposeRunner",
    "ComposePsRow",
    "ComposeRunner",
    "DefaultSpawner",
    "ContainerInspect",
    "ContainerStats",
    "ContainerSummary",
    "EngineClient",
    "GitRunner",
    "GitStatusReport",
    "ImageInspect",
    "ImageReference",
    "ImageSummary",
    "ImageValidationResult",
    "ImageValidator",
    "RealGitRunner",
    "RegistryCheckResult",
    "RegistryCheckStatus",
    "RegistryCheckStatusValues",
    "RegistryClient",
    "Spawner",
    "check_env_file_git_status",
    "create_engine_client",
    "create_image_validator",
    "create_registry_client",
    "default_spawner",
    "format_image_validation_error",
    "image_validation_warnings",
    "parse_image_reference",
]