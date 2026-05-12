"""PyInstaller entry point for RVC Cluster Debug Tool."""
import sys
from env_validation_tool.cli import main

if __name__ == "__main__":
    sys.exit(main() or 0)
