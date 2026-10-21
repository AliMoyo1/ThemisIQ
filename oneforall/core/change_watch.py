"""Tell the records connected to a record that it changed, from the function that updates it.

modules.governance.change_signals does the work; it is imported when the update runs, not where the update is defined, so a
module's data service does not import the governance module (and everything it reads) at start-up.
"""
import functools
import inspect


def watched(module: str, entity_type: str):
    """Decorator for an update function whose first argument is the record's id. The record is read before and after, and
    what changed that matters is published to the records connected to it. Publishing never raises into the update."""
    def decorate(update):
        first = next(iter(inspect.signature(update).parameters))

        @functools.wraps(update)
        def inner(*args, **kwargs):
            from modules.governance import change_signals
            with change_signals.watching(module, entity_type, args[0] if args else kwargs.get(first)):
                return update(*args, **kwargs)
        return inner
    return decorate
