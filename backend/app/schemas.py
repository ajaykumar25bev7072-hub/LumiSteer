"""Pydantic models: the single source of truth for default parameters and API validation.

Every physical default from the PRD lives here. Nothing related to simulating
a link is hardcoded elsewhere; UI controls and optimization bounds all read
from these models.
"""
from __future__ import annotations

import math
from typing import ClassVar, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Room(BaseModel):
    """Indoor room dimensions in meters."""
    width: float = Field(5.0, gt=0, description="x extent [m]")
    depth: float = Field(5.0, gt=0, description="y extent [m]")
    height: float = Field(3.0, gt=0, description="z extent [m]")


class LEDConfig(BaseModel):
    """Ceiling LED transmitter, Lambertian order m from half-power semi-angle."""
    position: Vec3 = Field(default_factory=lambda: Vec3(x=2.5, y=2.5, z=3.0))
    downward: bool = Field(True, description="LED fixed facing straight down; exposed tx tilt is handled only inside robust_optimize jitter")
    max_power_w: float = Field(1.0, gt=0)
    power_w: float = Field(1.0, ge=0.01, description="current transmit optical power [W]")
    dim_min_fraction: float = Field(0.10, gt=0, le=1.0, description="minimum dimming fraction of max_power_w")
    half_angle_deg: float = Field(60.0, gt=0, lt=90, description="Lambertian half-power semi-angle")


class Photodiode(BaseModel):
    area_m2: float = Field(1e-4, gt=0, description="photodiode area [m^2] (default 1 cm^2)")
    responsivity: float = Field(0.54, gt=0, le=1.0, description="[A/W]")
    fov_deg: float = Field(70.0, gt=0, lt=180, description="field of view semi-angle")
    filter_gain: float = Field(1.0, ge=0, description="optical filter gain Ts")
    concentrator_enabled: bool = False
    concentrator_fov_deg: float = Field(60.0, gt=0, lt=90)
    concentrator_refractive_index: float = Field(1.5, gt=1)


class Receiver(BaseModel):
    position: Vec3 = Field(default_factory=lambda: Vec3(x=3.2, y=2.5, z=0.8),
                           description="photodiode position [m]; faces up")
    height_min_m: float = Field(0.3, ge=0)
    height_max_m: float = Field(2.5, gt=0)
    photodiode: Photodiode = Field(default_factory=Photodiode)


class IRSConfig(BaseModel):
    enabled: bool = True
    rows: int = Field(8, ge=1, le=32)
    cols: int = Field(8, ge=1, le=32)
    element_area_m2: float = Field(9e-4, gt=0, description="per-element area [m^2] (default 3 cm x 3 cm)")
    reflectivity: float = Field(0.9, gt=0, le=1.0)
    sigma_deg: float = Field(5.0, gt=0, description="beam-spread sigma of the alignment Gaussian [deg]")
    wall: Literal["north", "south", "east", "west"] = "north"
    center: Vec3 = Field(default_factory=lambda: Vec3(x=2.5, y=0.12, z=2.0),
                         description="panel center [m]; y (for north/south) or x (for east/west) is snapped to the wall plane")
    azimuth_range_deg: Tuple[float, float] = (-75.0, 75.0)
    elevation_range_deg: Tuple[float, float] = (-75.0, 75.0)

    @property
    def n_elements(self) -> int:
        return self.rows * self.cols


class Obstacle(BaseModel):
    enabled: bool = False
    shape: Literal["circle", "box"] = "circle"
    center: Vec3 = Field(default_factory=lambda: Vec3(x=2.9, y=2.5, z=0.0))
    radius_m: float = Field(0.3, gt=0, description="circle radius [m]")
    box_semi_x: float = Field(0.25, gt=0)
    box_semi_y: float = Field(0.25, gt=0)
    height_m: float = Field(1.7, gt=0, description="obstacle height above floor [m]")
    attenuation: float = Field(0.0, ge=0, le=1, description="transmitted power fraction through the obstacle (0 = full block)")


class Noise(BaseModel):
    bandwidth_hz: float = Field(10e6, gt=0)
    ambient_class: Literal["low", "medium", "high"] = "medium"
    p_ambient_w: Optional[float] = Field(None, ge=0, description="override background optical power at RX [W]")
    load_resistance_ohm: float = Field(10_000.0, gt=0)
    temperature_k: float = Field(295.0, gt=0)

    AMBIENT_MAP: ClassVar[dict] = {"low": 1e-4, "medium": 1e-3, "high": 1e-2}

    def ambient_power(self) -> float:
        if self.p_ambient_w is not None:
            return self.p_ambient_w
        return self.AMBIENT_MAP[self.ambient_class]


class Modulation(BaseModel):
    scheme: Literal["ook"] = "ook"
    ber_threshold: float = Field(1e-3, gt=0, lt=0.5)


class Illumination(BaseModel):
    min_lux: float = Field(300.0, ge=0)
    max_lux: float = Field(1000.0, gt=0)
    luminous_efficacy: float = Field(264.0, gt=0, description="[lm/W] optical-to-photometric conversion")


class SimConfig(BaseModel):
    room: Room = Field(default_factory=Room)
    led: LEDConfig = Field(default_factory=LEDConfig)
    receiver: Receiver = Field(default_factory=Receiver)
    irs: IRSConfig = Field(default_factory=IRSConfig)
    obstacle: Obstacle = Field(default_factory=Obstacle)
    noise: Noise = Field(default_factory=Noise)
    modulation: Modulation = Field(default_factory=Modulation)
    illumination: Illumination = Field(default_factory=Illumination)

    @model_validator(mode="after")
    def check_bounds(self) -> "SimConfig":
        p = self.receiver.position
        if not (0 <= p.x <= self.room.width and 0 <= p.y <= self.room.depth
                and self.receiver.height_min_m <= p.z <= min(self.receiver.height_max_m, self.room.height)):
            raise ValueError("receiver position outside allowed bounds")
        lp = self.led.position
        if not (0 <= lp.x <= self.room.width and 0 <= lp.y <= self.room.depth and 0 <= lp.z <= self.room.height):
            raise ValueError("LED position outside room")
        return self

    def clamp_vertical(self) -> None:
        """Keep the receiver z inside allowed bounds; used when UI drags only x/y."""
        lo = self.receiver.height_min_m
        hi = min(self.receiver.height_max_m, self.room.height)
        self.receiver.position.z = min(max(self.receiver.position.z, lo), hi)


class IRSAngles(BaseModel):
    """Flat per-element tilt angles, row-major over the rows x cols grid."""
    azimuth_deg: List[float] = Field(default_factory=list)
    elevation_deg: List[float] = Field(default_factory=list)

    @classmethod
    def zeros(cls, n: int) -> "IRSAngles":
        return cls(azimuth_deg=[0.0] * n, elevation_deg=[0.0] * n)

    def filled(self, n: int) -> "IRSAngles":
        az = list(self.azimuth_deg[:n]) + [0.0] * max(0, n - len(self.azimuth_deg))
        el = list(self.elevation_deg[:n]) + [0.0] * max(0, n - len(self.elevation_deg))
        return IRSAngles(azimuth_deg=az, elevation_deg=el)


class LinkStatus:
    STABLE = "stable"
    DEGRADED = "degraded"
    OUTAGE = "outage"


class SimResult(BaseModel):
    received_power_w: float
    irradiance_w_m2: float
    illuminance_lux: float
    illuminance_ok: bool
    snr: float
    snr_db: float
    ber: Optional[float] = Field(None, description="None when underflowed to zero")
    g_los: float
    g_irs: float
    total_gain: float
    p_led_w: float
    link_status: str
    los_block_factor: float
    irs_block_factor: float
    noise_std: float


class SweepResult(BaseModel):
    resolution: int
    x: List[float]
    y: List[float]
    ber: List[List[Optional[float]]]
    received_power_w: List[List[float]]
    irradiance_w_m2: List[List[float]]
    outage_probability: float
    mean_ber: Optional[float]
    worst_ber: Optional[float]
    mean_power_w: float
    mean_irradiance_w_m2: float
    outage_positions: int


def q_function(x):
    """Q(x) = 0.5 * erfc(x / sqrt(2)); implemented with scipy.special.erfc."""
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def scipy_q(x):
    return 0.5 * erfc(x / math.sqrt(2.0))
