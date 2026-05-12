"""CPU feature detection via CPUID registers and microarchitecture mapping."""

from .specs import INTEL_MODEL_MAP


def get_cpu_microarch(model_number):
    """Map Intel CPU model number to microarchitecture name."""
    if model_number in INTEL_MODEL_MAP:
        return INTEL_MODEL_MAP[model_number]
    known = sorted(INTEL_MODEL_MAP.keys())
    for i in range(len(known) - 1, -1, -1):
        if model_number >= known[i]:
            return f"{INTEL_MODEL_MAP[known[i]]}+ (model {model_number})"
    return f"Unknown (model {model_number})"


def parse_cpuid_eax_family_model(eax_str):
    """Parse CPU family/model/stepping from CPUID.01H:EAX binary string.

    ESXi returns EAX as '0000:0000:0000:0110:0000:0110:1100:0001'
    (32 bits, MSB first).

    EAX bit layout:
      [3:0]   = Stepping
      [7:4]   = Base Model
      [11:8]  = Base Family
      [19:16] = Extended Model
      [27:20] = Extended Family

    Returns:
        (family, model, stepping) tuple, or (None, None, None) on parse error.
    """
    raw = eax_str.replace(":", "").replace(" ", "")
    clean = raw.replace("x", "0").replace("X", "0").replace("T", "1").replace("H", "0")
    try:
        val = int(clean, 2)
    except ValueError:
        return None, None, None

    stepping = val & 0xF
    base_model = (val >> 4) & 0xF
    base_family = (val >> 8) & 0xF
    ext_model = (val >> 16) & 0xF
    ext_family = (val >> 20) & 0xFF

    if base_family in (6, 15):
        display_model = (ext_model << 4) | base_model
    else:
        display_model = base_model

    if base_family == 15:
        display_family = ext_family + base_family
    else:
        display_family = base_family

    return display_family, display_model, stepping


# Feature flag definitions: (cpuid_level, register, bit_position)
FEATURE_CHECKS = {
    "aes":     (0x01, "ecx", 25),
    "sse4_2":  (0x01, "ecx", 20),
    "avx2":    (0x07, "ebx", 5),
    "avx512f": (0x07, "ebx", 16),
}


def detect_features_from_cpuid(cpuid_entries):
    """Detect CPU features from a list of CPUID entries.

    Args:
        cpuid_entries: list of objects with .level, .eax, .ebx, .ecx, .edx
                       attributes (e.g. from pyVmomi host.hardware.cpuFeature
                       or any equivalent source).

    Returns:
        dict with cpu_family, cpu_model_number, cpu_stepping, and
        boolean flags for each feature in FEATURE_CHECKS.
    """
    features = {}

    cpuid_by_level = {}
    for entry in (cpuid_entries or []):
        cpuid_by_level[entry.level] = entry

    # Family / Model / Stepping from CPUID.01H:EAX
    entry_01 = cpuid_by_level.get(0x01)
    if entry_01 and entry_01.eax:
        cpu_family, cpu_model, cpu_stepping = parse_cpuid_eax_family_model(
            entry_01.eax
        )
        features["cpu_family"] = cpu_family
        features["cpu_model_number"] = cpu_model
        features["cpu_stepping"] = cpu_stepping
    else:
        features["cpu_family"] = None
        features["cpu_model_number"] = None
        features["cpu_stepping"] = None

    # Feature bit checks
    for feat_name, (level, reg, bit) in FEATURE_CHECKS.items():
        entry = cpuid_by_level.get(level)
        if entry is None:
            features[feat_name] = False
            continue
        reg_val_str = getattr(entry, reg, None)
        if reg_val_str is None:
            features[feat_name] = False
            continue
        bits = reg_val_str.replace(":", "").replace(" ", "")
        bit_index = 31 - bit
        if bit_index < len(bits):
            features[feat_name] = bits[bit_index] == "1"
        else:
            features[feat_name] = False

    return features
