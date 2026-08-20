"""Flows with invariants that span more than one store.

`artwork` has to decode bytes, validate them against the reference specs, write an
object and reconcile a row — and undo cleanly if any of that fails. `publish` has to
claim a lock, read the whole catalogue, write two objects in order and record the
outcome. Neither belongs in a request handler.

Plain CRUD deliberately does **not** live here. `app/api/admin_content.py` talks to the
ORM directly because a create-or-409 is one statement plus one rule check, and routing
it through a service layer would add a file per endpoint and explain nothing.
"""
