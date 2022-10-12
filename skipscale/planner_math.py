from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from skipscale.utils import get_logger

log = get_logger(__name__)


def bounding_box(
    max_width: int, max_height: int, original_width: int, original_height: int
):
    """Figure out a size that fits in the requested box by maintaining original aspect
    ratio. If the requested width or height is 0, that dimension is unconstrainted."""
    if max_width == 0 or max_width > original_width:
        max_width = original_width
    if max_height == 0 or max_height > original_height:
        max_height = original_height
    if original_width * max_height > max_width * original_height:
        max_height = int(
            Decimal((max_width * original_height) / original_width).quantize(
                1, rounding=ROUND_HALF_UP
            )
        )
    else:
        max_width = int(
            Decimal((max_height * original_width) / original_height).quantize(
                1, rounding=ROUND_HALF_UP
            )
        )
    return max_width, max_height


def crop_box(
    crop_width: int, crop_height: int, original_width: int, original_height: int
):
    """Using the aspect ratio of the crop, calculate the source box for the crop."""
    original_ratio = original_width / original_height
    crop_ratio = crop_width / crop_height
    if original_ratio > crop_ratio:
        # the original is wider than the requested crop.
        # return the height of the original and reduce width by the crop ratio.
        h = original_height
        w = original_height * crop_ratio
    else:
        w = original_width
        h = original_width / crop_ratio
    return int(Decimal(w).quantize(1, rounding=ROUND_HALF_UP)), int(
        Decimal(h).quantize(1, rounding=ROUND_HALF_UP)
    )


def select_span(cropped_length, original_length, center_point):
    """
    Given a span of original_length pixels, choose a starting point for a new span
    of cropped_length with center_point as close to the center as possible.

    In this example we have an original span of 50 and want to crop that to 40:

    Original:
    |-----------------------------------X------------|

    Crop with ideal center point:
                    |-------------------X------------------|

    Clamped to actual leeway:
              |-------------------------X------------|

    If the original center point is 37/50 and the center point of the new span is
    21/40, a crop with the ideal center would start at 37 - 21 = 16. However, the
    crop is just 10 smaller than the original, so that's our positioning leeway.

    Original:
                 |------X-----------------------------------------|

    Crop with ideal center point:
    |-------------------X------------------|

    Clamped to actual leeway:
                 |------X-------------------------------|

    If the original center point is 8/50 and the center point of the new span is
    21/40, a crop with the ideal center would start at 8 - 21 = -13. This gets
    clamped to zero.
    """
    original_center_point = (
        original_length * center_point
    )  # center_point is a float 0..1
    ideal_center_point = cropped_length / 2
    leeway = original_length - cropped_length
    ideal_crop_origin = original_center_point - ideal_center_point
    clamped = min(max(ideal_crop_origin, 0), leeway)
    return round(clamped)


def crop_origin(
    cropped_width, cropped_height, original_width, original_height, center_x, center_y
) -> tuple[int, int]:
    # Since we only crop to get to a specific aspect ratio, we only ever crop in one of the dimensions.
    if cropped_width < original_width:
        return select_span(cropped_width, original_width, center_x), 0
    else:
        return 0, select_span(cropped_height, original_height, center_y)


@dataclass(frozen=True)
class ScaleDimensions:
    width: int
    height: int
    source_x: int
    source_y: int
    source_x2: int
    source_y2: int


def plan_scale(
    original_width: int,
    original_height: int,
    width: int | None = None,
    height: int | None = None,
    dpr: int | None = None,
    mode: Literal["crop"] | Literal["fit"] | Literal["stretch"] | None = None,
    center_x: float | None = None,
    center_y: float | None = None,
    max_pixel_ratio: int | None = None,
) -> ScaleDimensions:

    # Default source is the whole original image
    source_x = 0
    source_y = 0
    source_x2 = original_width
    source_y2 = original_height

    if dpr is not None:
        if max_pixel_ratio and dpr > max_pixel_ratio:
            dpr = max_pixel_ratio
    else:
        dpr = 1

    if width is not None:
        width = width * dpr
    else:
        width = 0

    if height is not None:
        height = height * dpr
    else:
        height = 0

    if mode == "crop" and center_x is None:
        center_x = 0.5

    if mode == "crop" and center_y is None:
        center_y = 0.5

    if mode == "stretch":
        # Freeform scaling but clamped to original image dimensions
        if width > original_width:
            width = original_width
        if height > original_height:
            height = original_height
    elif mode == "fit" or mode is None:
        # Fit mode
        width, height = bounding_box(width, height, original_width, original_height)
    else:
        # We are cropping, so the requested width/height describe both a bounding box *and* the requested aspect ratio.
        cropped_width, cropped_height = crop_box(
            width, height, original_width, original_height
        )
        # The final dimensions are either the requested dimensions or the source crop dimensions, whichever are smaller.
        if width > cropped_width or height > cropped_height:
            width = cropped_width
            height = cropped_height
        source_x, source_y = crop_origin(
            cropped_width,
            cropped_height,
            original_width,
            original_height,
            center_x,
            center_y,
        )
        source_x2 = source_x + (cropped_width - 1)
        source_y2 = source_y + (cropped_height - 1)

    scale_params = ScaleDimensions(
        width=width,
        height=height,
        source_x=source_x,
        source_y=source_y,
        source_x2=source_x2,
        source_y2=source_y2,
    )

    return scale_params
