"""Point d'entrée PyInstaller pour l'installeur terrain (§XXIX).

PyInstaller ne gèle pas `python -m package` : il lui faut un script avec un import ABSOLU du
package (pas les imports relatifs de __main__.py). Ce fichier ne sert qu'au packaging en .exe.
"""

import sys

from signflow_provision.cli import main

if __name__ == "__main__":
    sys.exit(main())
