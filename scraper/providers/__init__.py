from typing import Dict, Type
from .base import BaseCinemaProvider
from .aeon import AeonCinemaProvider
from .toho import TohoCinemaProvider
from .united import UnitedCinemaProvider

PROVIDER_REGISTRY: Dict[str, Type[BaseCinemaProvider]] = {
    "aeon": AeonCinemaProvider,
    "toho": TohoCinemaProvider,
    "united": UnitedCinemaProvider,
}


def get_provider(chain_id: str) -> BaseCinemaProvider:
    """chain_id に対応するProviderインスタンスを返す"""
    provider_cls = PROVIDER_REGISTRY.get(chain_id)
    if not provider_cls:
        available = ", ".join(PROVIDER_REGISTRY.keys()) or "none"
        raise ValueError(f"Unsupported chain_id: {chain_id!r} (available: {available})")
    return provider_cls()
