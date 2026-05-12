"""RVC Environment Validation Tool — a library for validating hypervisor
host hardware against Rubrik Virtual Cluster (RVC) minimum requirements.

Usage as CLI:
    python -m env_validation_tool --vcenter 10.4.111.202 ...

Usage as library:
    from env_validation_tool.discovery.esxi import ESXiDiscovery
    from env_validation_tool.validator import validate_requirements
"""

__version__ = "1.0.1"
