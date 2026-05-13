from setuptools import setup, find_packages

setup(
    name="env_validation_tool",
    version="1.0.6",
    description="Hypervisor Environment Validation & Troubleshoot Tool — collect ESXi/vCenter diagnostics and validate host hardware",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "pyVmomi>=8.0.0",
        "PyYAML>=5.4",
        "openpyxl>=3.1",
        "fpdf2>=2.7",
        "paramiko>=3.0",
        "requests>=2.28",
    ],
    entry_points={
        "console_scripts": [
            "env_validation_tool=env_validation_tool.cli:main",
        ],
    },
)
