from __future__ import annotations

from dataclasses import dataclass, field

from harness.application.ports import ArtifactNormalizer, QualityStrategy


@dataclass
class QualityStrategyRegistry:
    strategies: dict[str, QualityStrategy] = field(default_factory=dict)
    artifact_normalizers: list[ArtifactNormalizer] = field(default_factory=list)

    def register(self, strategy: QualityStrategy) -> None:
        if strategy.name in self.strategies:
            raise ValueError(f"duplicate quality policy: {strategy.name}")
        self.strategies[strategy.name] = strategy

    def register_normalizer(self, normalizer: ArtifactNormalizer) -> None:
        if any(item.name == normalizer.name for item in self.artifact_normalizers):
            raise ValueError(f"duplicate artifact normalizer: {normalizer.name}")
        self.artifact_normalizers.append(normalizer)

    def require(self, names: list[str]) -> tuple[QualityStrategy, ...]:
        unknown = sorted(set(names) - set(self.strategies))
        if unknown:
            raise ValueError(f"unknown quality policies: {', '.join(unknown)}")
        return tuple(self.strategies[name] for name in names)

    def normalizers(self) -> tuple[ArtifactNormalizer, ...]:
        return tuple(self.artifact_normalizers)
