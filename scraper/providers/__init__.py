from typing import Dict, Type
from .base import BaseCinemaProvider
from .aeon import AeonCinemaProvider
from .toho import TohoCinemaProvider
from .united import UnitedCinemaProvider
from .sunshine import CinemaSunshineProvider
from .tjoy import TJoyCinemaProvider
from .cinemas109 import Cinemas109Provider
from .smt import SmtCinemaProvider
from .other import OtherCinemaProvider

PROVIDER_REGISTRY: Dict[str, Type[BaseCinemaProvider]] = {
    "aeon": AeonCinemaProvider,
    "toho": TohoCinemaProvider,
    "united": UnitedCinemaProvider,
    "sunshine": CinemaSunshineProvider,
    "tjoy": TJoyCinemaProvider,
    "109cinemas": Cinemas109Provider,
    "smt": SmtCinemaProvider,
    "other": OtherCinemaProvider,
}



def get_provider(chain_id: str) -> BaseCinemaProvider:
    """chain_id に対応するProviderインスタンスを返す"""
    provider_cls = PROVIDER_REGISTRY.get(chain_id)
    if not provider_cls:
        available = ", ".join(PROVIDER_REGISTRY.keys()) or "none"
        raise ValueError(f"Unsupported chain_id: {chain_id!r} (available: {available})")
    return provider_cls()
