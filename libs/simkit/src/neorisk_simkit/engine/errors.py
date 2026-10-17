"""Engine exception types."""


class AbiViolation(Exception):
    """A kernel broke the action ABI (e.g. write before reject/RETRY)."""


class LoweringError(Exception):
    """Kernel source uses something the AST lowering pass cannot translate (Task 6)."""


class EngineError(Exception):
    """A run-level engine failure (bad addressing, invalid schedule).

    Generated code raises it with constant strings and runtime scalars mixed in `args` (Numba
    exceptions take no formatted strings), so the message is the arguments joined as text.
    """

    def __str__(self) -> str:
        return "".join(str(a) for a in self.args)


class CapExceeded(Exception):
    """A hard memory cap was hit; names the item (and the process, when known)."""

    def __init__(self, item: str, limit: int, attempted: int, process: str | None = None):
        self.item = item
        self.limit = limit
        self.attempted = attempted
        self.process = process
        msg = f"memory cap exceeded: {item} (limit {limit}, attempted {attempted})"
        if process is not None:
            msg += f" in process {process}"
        super().__init__(msg)


class LawViolation(Exception):
    """A required law failed (D47, exit code 4); cites the first offending row.

    State laws cite `table = "state <path>"`, `seq = -1` and `action_id = -1`."""

    def __init__(self, check_id: str, table: str, partition_id: int, seq: int, action_id: int,
                 detail: str):
        self.check_id = check_id
        self.table = table
        self.partition_id = partition_id
        self.seq = seq
        self.action_id = action_id
        self.detail = detail
        super().__init__(f"law {check_id} violated in {table} at (partition_id {partition_id}, "
                         f"seq {seq}), action {action_id}: {detail}")
