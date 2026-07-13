import logging
import os
import re
import yaml
from pathlib import Path

log = logging.getLogger(__name__)

# Matches ${VAR} or $VAR — these are the shapes os.path.expandvars touches.
_UNRESOLVED_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def load_config() -> dict:
    config_path_env = os.getenv("CAPTAINSNOW_CONFIG")
    if config_path_env:
        config_path = Path(config_path_env)
    else:
        config_path = Path("config.yaml")
        if not config_path.exists():
            pkg_dir = Path(__file__).parent.parent.parent
            config_path = pkg_dir / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found at {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    missing: set[str] = set()
    config = expand_env_vars(config, missing)
    if missing:
        # Loud, single startup warning — easy to spot in container logs.
        log.warning(
            "Captain Snow: %d env var(s) referenced in config.yaml are NOT SET — "
            "set them in your deploy environment and restart: %s",
            len(missing),
            ", ".join(sorted(missing)),
        )
    return config


def expand_env_vars(obj, missing: set | None = None):
    """Expand ${VAR} / $VAR. Unresolved vars are replaced with "" and recorded
    in `missing` so the loader can warn once at startup instead of letting
    literal "${STRIPE_API_KEY}" strings reach downstream SDKs."""
    if isinstance(obj, str):
        expanded = os.path.expandvars(obj)
        # If anything ${...}/$NAME survived, the env var didn't exist.
        leftovers = _UNRESOLVED_RE.findall(expanded)
        if leftovers:
            for braced, bare in leftovers:
                if missing is not None:
                    missing.add(braced or bare)
            # Blank out the whole value so SDKs reject it cleanly with
            # "missing credentials" rather than try to authenticate with
            # the literal string "${STRIPE_API_KEY}".
            expanded = _UNRESOLVED_RE.sub("", expanded).strip()
        return expanded
    elif isinstance(obj, dict):
        return {k: expand_env_vars(v, missing) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars(elem, missing) for elem in obj]
    return obj
