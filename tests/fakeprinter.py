"""The simulator ships with the workshop now (elegoo_lab.simulateur, `cc2 simulateur`); the tests still import it here."""

from elegoo_lab.simulateur import *  # noqa: F401,F403
from elegoo_lab.simulateur import main

if __name__ == "__main__":
    main()
