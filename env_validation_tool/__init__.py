"""Hypervisor Environment Validation & Troubleshoot Tool.

A library for collecting hypervisor host diagnostics (ESXi alarms, tasks,
performance, storage, network, VM details) and optionally validating
hardware against deployment-specific minimum requirements.

Usage as CLI:
    python -m env_validation_tool --vcenter 10.4.111.202 ...

Usage as library:
    from env_validation_tool.discovery.esxi import ESXiDiscovery
    from env_validation_tool.validator import validate_requirements
"""

__version__ = "1.0.1"
