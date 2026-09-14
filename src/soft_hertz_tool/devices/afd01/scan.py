"""AFD01 扫描点位：用 0.1° 整数单位按索引计算，不累计浮点误差。"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ScanAxis:
    """包含两端点的单轴范围；末段可短于步长。"""

    start: int
    end: int
    step: int

    @classmethod
    def degrees(cls, start: float, end: float, step: float, limit: float) -> "ScanAxis":
        """校验有限值/0.1°精度与范围，将正步长和端点转为整数单位。"""
        if (
            not all(math.isfinite(v) for v in (start, end, step))
            or abs(start) > limit
            or abs(end) > limit
            or step < 0.1
            or step > 2 * limit
        ):
            raise ValueError("扫描角度或步长越界")
        values = tuple(round(v * 10) for v in (start, end, step))
        if any(abs(v * 10 - n) > 1e-7 for v, n in zip((start, end, step), values)):
            raise ValueError("扫描参数精度为 0.1°")
        return cls(*values)

    @property
    def count(self) -> int:
        """包括起终点的点数；同点只扫描一次。"""
        return (abs(self.end - self.start) + self.step - 1) // self.step + 1

    def point(self, index: int) -> float:
        """按索引返回角度，末点钳制到终点，不生成范围外点。"""
        if not 0 <= index < self.count:
            raise IndexError(index)
        direction = 1 if self.end >= self.start else -1
        return (
            self.start + direction * min(index * self.step, abs(self.end - self.start))
        ) / 10


@dataclass(frozen=True)
class ScanGrid:
    """θ 外层、φ 内层的惰性栅格。"""

    theta: ScanAxis
    phi: ScanAxis

    @property
    def count(self) -> int:
        """总点数，不分配与点数等大的内存。"""
        return self.theta.count * self.phi.count

    def point(self, index: int) -> tuple[float, float]:
        """返回所选点的 θ/φ 度值。"""
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self.theta.point(index // self.phi.count), self.phi.point(
            index % self.phi.count
        )
