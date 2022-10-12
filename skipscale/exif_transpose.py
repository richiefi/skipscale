# from https://stackoverflow.com/a/30462851

import functools

from PIL import Image as PILImage
from PIL.Image import Image


def image_transpose_exif(im: Image) -> Image:
    """
    Apply Image.transpose to ensure 0th row of pixels is at the visual
    top of the image, and 0th column is the visual left-hand side.
    Return the original image if unable to determine the orientation.

    As per CIPA DC-008-2012, the orientation field contains an integer,
    1 through 8. Other values are reserved.

    Parameters
    ----------
    im: PIL.Image
       The image to be rotated.
    """

    exif_orientation_tag = 0x0112
    exif_transpose_sequences = [  # Val  0th row  0th col
        [],  #  0    (reserved)
        [],  #  1   top      left
        [PILImage.FLIP_LEFT_RIGHT],  #  2   top      right
        [PILImage.ROTATE_180],  #  3   bottom   right
        [PILImage.FLIP_TOP_BOTTOM],  #  4   bottom   left
        [PILImage.FLIP_LEFT_RIGHT, PILImage.ROTATE_90],  #  5   left     top
        [PILImage.ROTATE_270],  #  6   right    top
        [PILImage.FLIP_TOP_BOTTOM, PILImage.ROTATE_90],  #  7   right    bottom
        [PILImage.ROTATE_90],  #  8   left     bottom
    ]

    try:
        seq = exif_transpose_sequences[
            im._getexif()[exif_orientation_tag]  # type: ignore
        ]
    except Exception:
        return im
    else:
        return functools.reduce(type(im).transpose, seq, im)
