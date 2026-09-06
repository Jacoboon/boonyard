"""Enable ``python -m boonyardnn`` as an alias for the ``boonyardnn`` CLI."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
