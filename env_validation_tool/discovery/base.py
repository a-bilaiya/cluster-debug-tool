"""Abstract base class for hypervisor discovery backends.

Each hypervisor (ESXi, Hyper-V, AHV, KVM) implements this interface.
The validation, reporting, and network testing layers are hypervisor-agnostic
and only depend on the dict structures returned by these methods.
"""

from abc import ABC, abstractmethod


class HypervisorDiscovery(ABC):
    """Base class for hypervisor-specific hardware discovery."""

    @abstractmethod
    def connect(self, host, user, password, **kwargs):
        """Establish connection to the hypervisor management API.

        Args:
            host: IP or hostname of the hypervisor/management server.
            user: Username for authentication.
            password: Password for authentication.
            **kwargs: Backend-specific options (e.g. ssl_verify=False).
        """

    @abstractmethod
    def get_host_identity(self):
        """Return server identity information.

        Returns:
            dict with keys: name, vendor, model, service_tag, bios_ver
        """

    @abstractmethod
    def get_hypervisor_info(self):
        """Return hypervisor version information.

        Returns:
            dict with keys: name, version, build, api_version, full_name
        """

    @abstractmethod
    def get_cpu_info(self):
        """Return CPU hardware details.

        Returns:
            dict with keys: model, clock_ghz, sockets, cores, threads
        """

    @abstractmethod
    def get_cpu_features(self):
        """Return CPU feature flags and model identification.

        Returns:
            dict with keys: cpu_family, cpu_model_number, cpu_stepping,
                            aes, sse4_2, avx2, avx512f
        """

    @abstractmethod
    def get_memory_info(self):
        """Return total memory in GB.

        Returns:
            float — total memory in GB
        """

    @abstractmethod
    def get_storage_info(self):
        """Return list of storage devices.

        Returns:
            list of dicts, each with keys:
                name, model, vendor, capacity_gb, disk_type, is_ssd,
                protocol, role ('os' or 'data'), partitions
        """

    @abstractmethod
    def get_network_info(self):
        """Return network configuration.

        Returns:
            dict with keys:
                pnic — list of dicts (device, mac, link_speed_mb)
                vswitches — list of dicts (name, pnics, portgroups, mtu)
        """

    @abstractmethod
    def discover_vms(self, pattern, exclude_patterns=None):
        """Find VMs matching a name pattern (for post-deploy mode).

        Args:
            pattern: Substring to match in VM names.
            exclude_patterns: List of substrings to exclude.

        Returns:
            list of dicts with keys:
                vm_name, vm_ip, power_state, num_cpu, memory_mb
        """

    def disconnect(self):
        """Clean up connection resources. Override if needed."""
        pass

    def collect_host_report(self, vm_pattern=None, vm_exclude=None):
        """Convenience method: collect all host data into a single report dict.

        Subclasses normally don't need to override this.
        """
        from ..cpu_features import get_cpu_microarch

        report = {
            "host_identity": self.get_host_identity(),
            "hypervisor": self.get_hypervisor_info(),
            "cpu_details": self.get_cpu_info(),
            "memory_gb": self.get_memory_info(),
            "cpu_features": self.get_cpu_features(),
            "network": self.get_network_info(),
            "storage": self.get_storage_info(),
        }

        model_num = report["cpu_features"].get("cpu_model_number")
        if model_num is not None:
            report["cpu_details"]["microarchitecture"] = get_cpu_microarch(
                model_num
            )

        if vm_pattern:
            report["rvc_vms"] = self.discover_vms(
                vm_pattern, vm_exclude or []
            )
        else:
            report["rvc_vms"] = []

        return report
