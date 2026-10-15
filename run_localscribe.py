"""Entry point for PyInstaller and for running from source: python run_localscribe.py"""

import sys

from localscribe.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
