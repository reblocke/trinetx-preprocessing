"""Spawn-safe transfer helpers for already-held process lock descriptors."""

from __future__ import annotations

from multiprocessing.reduction import DupFd
from typing import Any


class SpawnedLockFileDescriptor:
    """Duplicate one held lock descriptor through the spawn pass-fd channel."""

    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    def __reduce__(self):
        return (_detach_duplicated_file_descriptor, (DupFd(self.descriptor),))


def duplicate_lock_file_descriptors_for_spawn(
    descriptors: tuple[int, ...],
) -> tuple[SpawnedLockFileDescriptor, ...]:
    """Wrap held descriptors so a spawned child retains the same file locks."""

    return tuple(SpawnedLockFileDescriptor(descriptor) for descriptor in descriptors)


def _detach_duplicated_file_descriptor(duplicated_descriptor: Any) -> int:
    return int(duplicated_descriptor.detach())
