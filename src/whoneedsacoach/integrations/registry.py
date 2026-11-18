from pathlib import Path

from whoneedsacoach.integrations.garmin import GarminAdapter


class ProviderRegistry:
    def __init__(self, repo, tokens_root: Path, adapters: dict | None = None):
        self.repo = repo
        self.tokens_root = Path(tokens_root)
        if adapters is not None:
            self._adapters = adapters
        else:
            garmin = GarminAdapter(repo, tokens_root)
            self._adapters = {garmin.name: garmin}

    def get(self, provider: str):
        return self._adapters.get(provider)

    def known(self) -> list[str]:
        return sorted(self._adapters)


def build_registry(repo, tokens_root: Path) -> ProviderRegistry:
    return ProviderRegistry(repo, tokens_root)
