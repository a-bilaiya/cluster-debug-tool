"""Allow running as: python -m env_validation_tool"""

import sys
from .cli import main

sys.exit(main())
