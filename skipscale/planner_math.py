from decimal import Decimal, ROUND_HALF_UP

from skipscale.utils import get_logger

log = get_logger(__name__)


def bounding_box(max_width, max_height, original_width, original_height):
    """Figure out a size that fits in the requested box by maintaining original aspect
    ratio. If the requested width or height is 0, that dimension is unconstrainted."""
    if max_width == 0 or max_width > original_width:
        max_width = original_width
    if max_height == 0 or max_height > original_height:
        max_height = original_height
    if original_width * max_height > max_width * original_height:
        max_height = (max_width * original_height) / original_width
    else:
        max_width = (max_height * original_width) / original_height
    return int(Decimal(max_width).quantize(1, rounding=ROUND_HALF_UP)), int(Decimal(max_height).quantize(1, rounding=ROUND_HALF_UP))

def crop_box(crop_width, crop_height, original_width, original_height):
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
    return int(Decimal(w).quantize(1, rounding=ROUND_HALF_UP)), int(Decimal(h).quantize(1, rounding=ROUND_HALF_UP))

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
    original_center_point = original_length * center_point # center_point is a float 0..1
    ideal_center_point = cropped_length / 2
    leeway = original_length - cropped_length
    ideal_crop_origin = original_center_point - ideal_center_point
    clamped = min(max(ideal_crop_origin, 0), leeway)
    return round(clamped)

def crop_origin(cropped_width, cropped_height, original_width, original_height, center_x, center_y):
    # Since we only crop to get to a specific aspect ratio, we only ever crop in one of the dimensions.
    if cropped_width < original_width:
        return select_span(cropped_width, original_width, center_x), 0
    else:
        return 0, select_span(cropped_height, original_height, center_y)

def plan_scale(query, imageinfo, max_pixel_ratio=None):
    if 'dpr' in query:
        if max_pixel_ratio and query['dpr'] > max_pixel_ratio:
            dpr = max_pixel_ratio
        else:
            dpr = query['dpr']
    else:
        dpr = 1

    if 'width' in query:
        width = query['width'] * dpr
        assert width >= 0, f"invalid width, query={query}"
    else:
        width = 0

    if 'height' in query:
        height = query['height'] * dpr
        assert height >= 0, f"invalid height, query={query}"
    else:
        height = 0

    if 'mode' in query and query['mode'] == 'crop' and not 'center-x' in query:
        query['center-x'] = 0.5
        query['center-y'] = 0.5

    do_stretch = query.get('mode') == 'stretch'
    if do_stretch and (width <= 0 or height <= 0):
        # Avoid failing later on if clients send a silly combination of parameters
        log.warning('plan_scale: invalid width/height with mode=stretch, '
                    'forcing fit mode (query: %s)', query)
        do_stretch = False

    if do_stretch:
        # Freeform scaling but clamped to original image dimensions
        if width < imageinfo['width']:
            w = width
        else:
            w = imageinfo['width']
        if height < imageinfo['height']:
            h = height
        else:
            h = imageinfo['height']
        return {'width': w, 'height': h}

    if 'center-x' not in query:
        box_w, box_h = bounding_box(width, height, imageinfo['width'], imageinfo['height'])
        return {'width': box_w, 'height': box_h}

    # We are cropping, so the requested width/height describe both a bounding box *and* the requested aspect ratio.
    cropped_width, cropped_height = crop_box(width, height, imageinfo['width'], imageinfo['height'])
    # The final dimensions are either the requested dimensions or the source crop dimensions, whichever are smaller.
    scale_params = {}
    if cropped_width > width or cropped_height > height:
        scale_params['width'] = width
        scale_params['height'] = height
    else:
        scale_params['width'] = cropped_width
        scale_params['height'] = cropped_height
    crop = list(crop_origin(cropped_width, cropped_height, imageinfo['width'], imageinfo['height'],
                            query['center-x'], query['center-y']))
    crop.extend([crop[0] + (cropped_width - 1), crop[1] + (cropped_height - 1)])
    scale_params['crop'] = ",".join(map(str, crop))

    return scale_params
