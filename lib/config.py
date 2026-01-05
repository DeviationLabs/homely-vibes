#!/usr/bin/env python3
"""
OmegaConf-based configuration system for homely-vibes.

Replaces the old Constants.py pattern with hierarchical YAML configs:
- config/default.yaml: Safe defaults (checked into git)
- config/local.yaml: Secrets and overrides (gitignored)

Usage:
    from lib.config import get_config

    cfg = get_config()
    email = cfg.tesla.tesla_email
    tokens = cfg.pushover.tokens
"""

import os
from dataclasses import dataclass, is_dataclass
from enum import StrEnum
from typing import Dict, get_origin, get_args

from omegaconf import OmegaConf


class NodeType(StrEnum):
    """Node type enumeration"""

    FOSCAM = "foscam"
    WINDOWS = "windows"
    GENERIC = "generic"


class OpMode(StrEnum):
    """Tesla Powerwall operation mode"""

    AUTONOMOUS = "autonomous"
    SELF_CONSUMPTION = "self_consumption"


@dataclass
class PathsConfig:
    """File paths and directories"""

    home: str
    logging_dir: str
    tuya_log_base: str
    json_summary_file: str
    json_summary_patch_file: str
    json_pumprates_file: str
    rachio_events_cmd: str


@dataclass
class EmailConfig:
    """Email configuration"""

    from_addr: str
    to_addr: str
    gmail_username: str
    gmail_password: str


@dataclass
class TwilioConfig:
    """Twilio SMS configuration"""

    sid: str
    auth_token: str
    sms_from: str


@dataclass
class PushoverConfig:
    """Pushover notification configuration"""

    user: str
    delivery_group: str
    default_token: str
    tokens: Dict[str, str]


@dataclass
class NodeConfig:
    """Individual node configuration"""

    ip: str
    node_type: NodeType
    username: str | None = None
    password: str | None = None


@dataclass
class FoscamConfig:
    """Foscam camera configuration"""

    username: str
    password: str
    foscam_dir: str
    purge_after_days: int


@dataclass
class WindowsConfig:
    """Windows node credentials"""

    username: str
    password: str


@dataclass
class NodeCheckConfig:
    """Node monitoring configuration"""

    foscam: FoscamConfig
    windows: WindowsConfig
    node_configs: Dict[str, NodeConfig]
    nodes: Dict[str, dict]


@dataclass
class WaterMonitorConfig:
    """Water monitoring and alerting thresholds"""

    max_zones: int
    max_new_files: int
    logrotate_per_day: int
    days_lookback: int
    start_from_epoch: int
    days_email_report: int
    min_drip_zone_alert_time: int
    min_drip_plot_time: int
    min_misc_zone_alert_time: int
    min_sprinkler_zone_alert_time: int
    alert_thresh: float
    pump_alert: int
    pump_toggles_count: int


@dataclass
class OpModeConfig:
    """Tesla Powerwall operation mode configuration"""

    time_start: int
    time_end: int
    pct_gradient_per_hr: int
    pct_thresh: int
    iff_higher: bool
    pct_min: int
    pct_min_trail_stop: int
    op_mode: OpMode
    reason: str
    always_notify: bool


@dataclass
class TeslaConfig:
    """Tesla Powerwall configuration"""

    powerwall_ip: str
    powerwall_email: str
    powerwall_password: str
    powerwall_sms_rcpt: str
    powerwall_poll_time: int
    tesla_email: str
    tesla_password: str
    tesla_token_file: str
    decision_points: list[OpModeConfig]


@dataclass
class AugustConfig:
    """August Smart Locks configuration"""

    email: str
    password: str
    phone: str
    token_file: str


@dataclass
class SamsungFrameConfig:
    """Samsung Frame TV configuration"""

    ip: str
    port: int
    token_file: str
    default_matte: str
    supported_formats: list[str]
    max_image_size_mb: int


@dataclass
class RachioConfig:
    """Rachio irrigation system configuration"""

    api_key: str
    rachio_id: str


@dataclass
class FlumeConfig:
    """Flume water monitoring configuration"""

    client_id: str
    client_secret: str
    user_email: str
    password: str


@dataclass
class NetworkCheckConfig:
    """Network bandwidth monitoring configuration"""

    min_dl_bw: int
    min_ul_bw: int


@dataclass
class BrowserAlertConfig:
    """Browser activity monitoring configuration"""

    refresh_delay: int
    min_reporting_gap: int
    hr_start_monitoring: int
    hr_stop_monitoring: int
    hr_email: int
    blacklist: list[str]


@dataclass
class Config:
    """Root configuration for homely-vibes"""

    paths: PathsConfig
    email: EmailConfig
    twilio: TwilioConfig
    pushover: PushoverConfig
    node_check: NodeCheckConfig
    water_monitor: WaterMonitorConfig
    tesla: TeslaConfig
    august: AugustConfig
    samsung_frame: SamsungFrameConfig
    rachio: RachioConfig
    flume: FlumeConfig
    network_check: NetworkCheckConfig
    browser_alert: BrowserAlertConfig
    my_external_ip: str
    seconds_in_day: int


# Singleton configuration instance
_config: Config | None = None


def get_config() -> Config:
    """
    Get application configuration singleton.

    Loads from config/default.yaml with optional config/local.yaml overrides.
    Config is cached after first load.

    Returns:
        Config: Application configuration
    """
    global _config
    if _config is None:
        config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config"))

        # Load default config
        default_path = os.path.join(config_dir, "default.yaml")
        local_path = os.path.join(config_dir, "local.yaml")

        # Load default configuration
        cfg_omega = OmegaConf.load(default_path)

        # Merge with local config if it exists
        if os.path.exists(local_path):
            local_cfg = OmegaConf.load(local_path)
            cfg_omega = OmegaConf.merge(cfg_omega, local_cfg)

        # Convert OmegaConf to Config dataclass
        # We use to_container to get a dict, then instantiate the dataclass
        cfg_dict = OmegaConf.to_container(cfg_omega, resolve=True)

        # Create Config instance from dict
        # Note: We need to manually construct nested dataclasses
        _config = _dict_to_config(cfg_dict)

    return _config


def _dict_to_config(cfg_dict: dict) -> Config:  # type: ignore
    """
    Convert configuration dictionary to Config dataclass.

    Handles nested dataclass construction.
    """

    # Helper to convert nested dicts to dataclasses
    def build_nested(data: dict, cls: type) -> object:  # type: ignore
        """Recursively build nested dataclasses"""
        kwargs = {}
        for field_name, field_type in cls.__annotations__.items():
            if field_name not in data:
                continue

            value = data[field_name]

            # Check if it's a generic type like list[OpModeConfig]
            origin = get_origin(field_type)

            if origin is list:
                # Handle list[SomeDataclass]
                args = get_args(field_type)
                if args and is_dataclass(args[0]):
                    # Convert each dict in the list to the dataclass
                    item_class = args[0]
                    kwargs[field_name] = [build_nested(item, item_class) for item in value]
                else:
                    # Plain list (e.g., list[str])
                    kwargs[field_name] = value
            elif origin is dict:
                # Handle Dict[str, SomeDataclass] types
                args = get_args(field_type)
                if len(args) >= 2 and is_dataclass(args[1]):
                    value_class: type = args[1]  # type: ignore[assignment]
                    kwargs[field_name] = {k: build_nested(v, value_class) for k, v in value.items()}
                else:
                    kwargs[field_name] = value
            elif is_dataclass(field_type):
                # Nested dataclass
                kwargs[field_name] = build_nested(value, field_type)
            elif isinstance(field_type, type) and issubclass(field_type, StrEnum):
                # StrEnum - convert string to enum
                kwargs[field_name] = field_type(value)
            else:
                # Primitive type
                kwargs[field_name] = value

        return cls(**kwargs)

    return build_nested(cfg_dict, Config)  # type: ignore


def reset_config() -> None:
    """Reset configuration singleton (useful for testing)"""
    global _config
    _config = None
