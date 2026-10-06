"""One atomic, event-loop-local capacity set shared by production runtimes."""
import asyncio
from app.services.teacher_work.runs import WorkRunError


class InstanceRunCapacity:
    def __init__(self, capacity, *, loop=None):
        if type(capacity) is not int or not 1 <= capacity <= 4:
            raise WorkRunError('PROPOSAL_RUNTIME_UNAVAILABLE', 503)
        self.capacity, self.loop = capacity, loop
        self.slots = set()
        self.owners = set()

    def acquire(self):
        if len(self.slots) >= self.capacity:
            raise WorkRunError('INSTANCE_BUSY', 429)
        slot = object()
        self.slots.add(slot)
        return slot


_shared_capacity = None


def get_shared_capacity(capacity):
    global _shared_capacity
    if type(capacity) is not int or capacity < 1:
        raise WorkRunError('PROPOSAL_RUNTIME_UNAVAILABLE', 503)
    capacity, loop = min(capacity, 4), asyncio.get_running_loop()
    pool = _shared_capacity
    if pool is not None:
        if pool.loop is loop and pool.capacity == capacity:
            return pool
        safe = not pool.slots and (pool.loop.is_closed() or all(owner.closed for owner in pool.owners))
        if not safe:
            raise WorkRunError('PROPOSAL_RUNTIME_UNAVAILABLE', 503)
    _shared_capacity = InstanceRunCapacity(capacity, loop=loop)
    return _shared_capacity
