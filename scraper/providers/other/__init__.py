from datetime import date
from typing import Any, Dict, List, Optional, Tuple, Type

from ...models import MovieSchedule
from ...sanitizer import sanitize_identifier
from ..base import BaseCinemaProvider
from .base import BaseOtherStrategy
from .cinema_frontier import (
    CinemaFrontierStrategy,
    clean_cinema_frontier_title,
    map_cinema_frontier_seat_status,
    normalize_cinema_frontier_screen_name,
    parse_cinema_frontier_schedule_html,
)
from .oscinemas import (
    OsCinemasStrategy,
    map_oscinemas_seat_status,
    parse_oscinemas_schedule_html,
)
from .smt_legacy import (
    SmtLegacyStrategy,
    map_smt_legacy_seat_status,
    parse_smt_legacy_schedule_html,
)

STRATEGY_REGISTRY: Dict[str, Type[BaseOtherStrategy]] = {
    SmtLegacyStrategy.ADAPTER_ID: SmtLegacyStrategy,
    CinemaFrontierStrategy.ADAPTER_ID: CinemaFrontierStrategy,
    OsCinemasStrategy.ADAPTER_ID: OsCinemasStrategy,
}


class OtherCinemaProvider(BaseCinemaProvider):
    """
    共同経営・独立系劇場（other）向け統合 Provider（Strategy パターンの Context）。
    劇場マスタの 'adapter' 属性に応じて STRATEGY_REGISTRY から適切な Strategy へ委譲する。
    """

    CHAIN_ID: str = "other"

    def __init__(
        self,
        timeout: int = 15,
        strategy_registry: Optional[Dict[str, Type[BaseOtherStrategy]]] = None,
    ):
        super().__init__(timeout=timeout)
        self.strategy_registry: Dict[str, Type[BaseOtherStrategy]] = dict(
            strategy_registry
            if strategy_registry is not None
            else STRATEGY_REGISTRY
        )
        self._strategies: Dict[str, BaseOtherStrategy] = {}

    def _resolve_theater_and_strategy(
        self, theater_id: str
    ) -> Tuple[Dict[str, Any], BaseOtherStrategy]:
        safe_theater = sanitize_identifier(theater_id)
        info = self.get_theater_info(safe_theater)
        adapter = str(info.get("adapter") or "").strip()
        strategy_cls = self.strategy_registry.get(adapter)
        if strategy_cls is None:
            raise ValueError(
                f"Unsupported adapter '{adapter}' for theater '{safe_theater}'"
            )

        if adapter not in self._strategies:
            self._strategies[adapter] = strategy_cls(timeout=self.timeout)
        return info, self._strategies[adapter]

    def build_booking_url(
        self,
        theater_id: str,
        event_id: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> str:
        info, strategy = self._resolve_theater_and_strategy(theater_id)
        return strategy.build_booking_url(info, event_id, extra_params)

    def build_movie_info_url(
        self, theater_id: str, raw_href: Optional[str]
    ) -> str:
        info, strategy = self._resolve_theater_and_strategy(theater_id)
        return strategy.build_movie_info_url(info, raw_href)

    def fetch_movies(self, theater_id: str, target_date: date) -> List[MovieSchedule]:
        info, strategy = self._resolve_theater_and_strategy(theater_id)
        return strategy.fetch_movies(info, target_date)


__all__ = [
    "BaseOtherStrategy",
    "CinemaFrontierStrategy",
    "OsCinemasStrategy",
    "OtherCinemaProvider",
    "STRATEGY_REGISTRY",
    "SmtLegacyStrategy",
    "clean_cinema_frontier_title",
    "map_cinema_frontier_seat_status",
    "map_oscinemas_seat_status",
    "map_smt_legacy_seat_status",
    "normalize_cinema_frontier_screen_name",
    "parse_cinema_frontier_schedule_html",
    "parse_oscinemas_schedule_html",
    "parse_smt_legacy_schedule_html",
]
