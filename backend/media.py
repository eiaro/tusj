"""What is loaded in the printer: tape width, endless or die-cut, resolution, colours."""
from dataclasses import dataclass

from brother_ql.labels import Color, FormFactor, LabelsManager

from i18n import AppError

DPI = 300
DOTS_PER_MM = DPI / 25.4


@dataclass(frozen=True)
class Media:
    id: str                 # brother_ql label identifier, e.g. "62", "29", "62x29"
    tape_mm: float          # physical tape width
    width_px: int           # printable width
    height_px: int | None   # printable height for die-cut labels; None for endless tape
    feed_px: int            # blank tape the printer feeds before and after an endless label
    two_color: bool         # black/red tape

    @property
    def endless(self) -> bool:
        return self.height_px is None

    @property
    def printable_mm(self) -> float:
        return self.width_px / DOTS_PER_MM

    @classmethod
    def from_label(cls, label_id: str) -> "Media":
        label_id = str(label_id)
        try:
            spec = LabelsManager()[label_id]
        except KeyError:
            raise AppError(400, "unknown_media", f"Unknown label type '{label_id}'", media=label_id)
        endless = spec.form_factor == FormFactor.ENDLESS
        return cls(
            id=label_id,
            tape_mm=spec.tape_size[0],
            width_px=spec.dots_printable[0],
            height_px=None if endless else spec.dots_printable[1],
            feed_px=spec.feed_margin if endless else 0,
            two_color=spec.color == Color.BLACK_RED_WHITE,
        )

    def dimensions(self, image_height_px: int) -> dict:
        """Physical size of the printed label in mm, including blank feed for endless tape."""
        if self.endless:
            feed_mm = self.feed_px / DOTS_PER_MM
            length_mm = image_height_px / DOTS_PER_MM + 2 * feed_mm
        else:
            length_mm = self.height_px / DOTS_PER_MM
            feed_mm = (length_mm - image_height_px / DOTS_PER_MM) / 2
        return {
            "tape": round(self.tape_mm, 1),
            "printable": round(self.printable_mm, 1),
            "length": round(length_mm, 1),
            "feed": round(feed_mm, 1),
        }
