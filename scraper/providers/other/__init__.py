from datetime import date
from typing import Any, Dict, List, Optional, Tuple, Type

from ...models import MovieSchedule, TheaterScheduleResponse
from ...sanitizer import sanitize_identifier
from ..base import BaseCinemaProvider
from .cinema_frontier import (
    CinemaFrontierProvider,
    clean_cinema_frontier_title,
    map_cinema_frontier_seat_status,
    normalize_cinema_frontier_screen_name,
    parse_cinema_frontier_schedule_html,
)
from .oscinemas import (
    OsCinemasProvider,
    map_oscinemas_seat_status,
    parse_oscinemas_schedule_html,
)
from .smt_legacy import (
    SmtLegacyProvider,
    map_smt_legacy_seat_status,
    parse_smt_legacy_schedule_html,
)

ADAPTER_REGISTRY: Dict[str, Type[BaseCinemaProvider]] = {
    SmtLegacyProvider.ADAPTER_ID: SmtLegacyProvider,
    CinemaFrontierProvider.ADAPTER_ID: CinemaFrontierProvider,
    OsCinemasProvider.ADAPTER_ID: OsCinemasProvider,
}


class OtherCinemaProvider(BaseCinemaProvider):
    """
    共同経営・独立系劇場（other）向け統合 Provider。
    劇場マスタの 'adapter' 属性に応じて ADAPTER_REGISTRY から適切な Provider へ委譲する。
    """

    CHAIN_ID: str = "other"

    def __init__(
        self,
        timeout: int = 15,
        adapter_registry: Optional[Dict[str, Type[BaseCinemaProvider]]] = None,
    ):
        super().__init__(timeout=timeout)
        self.adapter_registry: Dict[str, Type[BaseCinemaProvider]] = dict(
            adapter_registry
            if adapter_registry is not None
            else ADAPTER_REGISTRY
        )
        self._providers: Dict[str, BaseCinemaProvider] = {}

    def _resolve_provider(
        self, theater_id: str
    ) -> Tuple[Dict[str, Any], BaseCinemaProvider]:
        safe_theater = sanitize_identifier(theater_id)
        info = self.get_theater_info(safe_theater)
        adapter = str(info.get("adapter") or "").strip()
        provider_cls = self.adapter_registry.get(adapter)
        if provider_cls is None:
            raise ValueError(
                f"Unsupported adapter '{adapter}' for theater '{safe_theater}'"
            )

        if adapter not in self._providers:
            self._providers[adapter] = provider_cls(timeout=self.timeout)
        provider = self._providers[adapter]
        if self._theaters_cache is not None:
            provider._theaters_cache = self._theaters_cache
        else:
            merged = dict(provider._theaters_cache or {})
            merged[safe_theater] = info
            provider._theaters_cache = merged
        return info, provider

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        _, provider = self._resolve_provider(theater_id)
        return provider.build_booking_url(theater_id, event_id, extra_params)

    def build_movie_info_url(
        self, theater_id: str, raw_href: Optional[str]
    ) -> str:
        _, provider = self._resolve_provider(theater_id)
        return provider.resolve_movie_info_url(theater_id, raw_href)

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        _, provider = self._resolve_provider(theater_id)
        return provider.fetch_movies(theater_id, target_date)

    def get_schedule_response(
        self, theater_id: str, target_date: date
    ) -> TheaterScheduleResponse:
        _, provider = self._resolve_provider(theater_id)
        return provider.get_schedule_response(theater_id, target_date)


__all__ = [
    "ADAPTER_REGISTRY",
    "CinemaFrontierProvider",
    "OsCinemasProvider",
    "OtherCinemaProvider",
    "SmtLegacyProvider",
    "clean_cinema_frontier_title",
    "map_cinema_frontier_seat_status",
    "map_oscinemas_seat_status",
    "map_smt_legacy_seat_status",
    "normalize_cinema_frontier_screen_name",
    "parse_cinema_frontier_schedule_html",
    "parse_oscinemas_schedule_html",
    "parse_smt_legacy_schedule_html",
]
