"""Deliberately permissive stand-in for numpy.

This project does not import numpy. On a developer machine numpy is often
installed anyway, pulled in transitively by unrelated tooling, and its bundled
stubs use Python 3.12-only syntax. Because the project type-checks at
``python_version = 3.11``, mypy then fails on a file it has no reason to read,
which makes ``mypy src tests`` fail for reasons unrelated to this code.

Putting this stub earlier on ``MYPYPATH`` (see ``scripts/test.ps1``) removes that
environment-dependent failure.

Consequence to be aware of: if numpy is ever genuinely imported here, mypy will
treat it as an untyped module rather than checking it. That is intentional. An
automatic trading bridge has no business depending on numpy, and a permissive
stub keeps that decision visible in review instead of implicit.
"""

from typing import Any

def __getattr__(name: str) -> Any: ...
