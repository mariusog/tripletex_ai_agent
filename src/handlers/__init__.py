"""Handler registry for Tripletex task types.

Maps task_type strings to handler instances. Importing this package
triggers auto-registration of all implemented handlers.
"""

# Import handler modules to trigger @register_handler decorators
from src.handlers import (  # noqa: F401
    asset,
    bank,
    customer,
    delete,
    department,
    employee,
    invoice,
    ledger,
    module,
    order,
    product,
    project,
    reporting,
    salary,
    travel,
)
from src.handlers.base import HANDLER_REGISTRY, BaseHandler, get_handler, register_handler

__all__ = [
    "HANDLER_REGISTRY",
    "BaseHandler",
    "get_handler",
    "register_handler",
]
