from skipscale.planner_math import plan_scale


def test_square_linear_downscale():
    request = {"width": 200, "height": 200}
    result = plan_scale(1000, 1000, **request)
    assert result.width == 200
    assert result.height == 200


def test_square_linear_upscale():
    request = {"width": 1000, "height": 1000}
    result = plan_scale(200, 200, **request)
    assert result.width == 200
    assert result.height == 200


def test_square_wide_downscale():
    request = {"width": 500, "height": 200}
    result = plan_scale(1000, 1000, **request)
    assert result.width == 200
    assert result.height == 200


def test_square_wide_upscale():
    request = {"width": 1500, "height": 500}
    result = plan_scale(200, 200, **request)
    assert result.width == 200
    assert result.height == 200


def test_square_tall_downscale():
    request = {"width": 200, "height": 500}
    result = plan_scale(1000, 1000, **request)
    assert result.width == 200
    assert result.height == 200


def test_square_tall_upscale():
    request = {"width": 500, "height": 1500}
    result = plan_scale(200, 200, **request)
    assert result.width == 200
    assert result.height == 200


def test_wide_square_downscale():
    request = {"width": 400, "height": 400}
    result = plan_scale(1920, 1080, **request)
    assert result.width == 400
    assert result.height == 225


def test_wide_square_upscale():
    request = {"width": 4000, "height": 4000}
    result = plan_scale(1920, 1080, **request)
    assert result.width == 1920
    assert result.height == 1080


def test_tall_square_downscale():
    request = {"width": 400, "height": 400}
    result = plan_scale(1080, 1920, **request)
    assert result.width == 225
    assert result.height == 400


def test_tall_square_upscale():
    request = {"width": 4000, "height": 4000}
    result = plan_scale(1080, 1920, **request)
    assert result.width == 1080
    assert result.height == 1920


def test_dpr():
    request = {"width": 500, "height": 500, "dpr": 3}
    result = plan_scale(1920, 1080, **request)
    assert result.width == 1500
    assert result.height == 844


def test_max_dpr():
    request = {"width": 500, "height": 500, "dpr": 3}
    max_dpr = 2
    result = plan_scale(1920, 1080, max_pixel_ratio=max_dpr, **request)
    assert result.width == 1000
    assert result.height == 563


def test_tall_square_stretch_downscale():
    request = {"width": 400, "height": 400, "mode": "stretch"}
    result = plan_scale(1080, 1920, **request)
    assert result.width == 400
    assert result.height == 400


def test_tall_square_stretch_upscale():
    request = {"width": 4000, "height": 4000, "mode": "stretch"}
    result = plan_scale(1080, 1920, **request)
    assert result.width == 1080
    assert result.height == 1920


def test_wide_square_crop_middle_downscale():
    request = {
        "width": 200,
        "height": 200,
        "center_x": 0.5,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 200
    assert result.height == 200
    assert result.source_x == 420
    assert result.source_y == 0
    assert result.source_x2 == 1499
    assert result.source_y2 == 1079


def test_wide_square_crop_middle_upscale():
    request = {
        "width": 2000,
        "height": 2000,
        "center_x": 0.5,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 1080
    assert result.height == 1080
    assert result.source_x == 420
    assert result.source_y == 0
    assert result.source_x2 == 1499
    assert result.source_y2 == 1079


def test_wide_square_crop_left_downscale():
    request = {
        "width": 200,
        "height": 200,
        "center_x": 0.1,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 200
    assert result.height == 200
    assert result.source_x == 0
    assert result.source_y == 0
    assert result.source_x2 == 1079
    assert result.source_y2 == 1079


def test_wide_square_crop_left_upscale():
    request = {
        "width": 2000,
        "height": 2000,
        "center_x": 0.1,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 1080
    assert result.height == 1080
    assert result.source_x == 0
    assert result.source_y == 0
    assert result.source_x2 == 1079
    assert result.source_y2 == 1079


def test_wide_square_crop_right_downscale():
    request = {
        "width": 200,
        "height": 200,
        "center_x": 0.9,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 200
    assert result.height == 200
    assert result.source_x == 840
    assert result.source_y == 0
    assert result.source_x2 == 1919
    assert result.source_y2 == 1079


def test_wide_square_crop_right_upscale():
    request = {
        "width": 2000,
        "height": 2000,
        "center_x": 0.9,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 1080
    assert result.height == 1080
    assert result.source_x == 840
    assert result.source_y == 0
    assert result.source_x2 == 1919
    assert result.source_y2 == 1079


def test_tall_wide_crop_middle_downscale():
    request = {
        "width": 960,
        "height": 540,
        "center_x": 0.5,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1080, 1920, **request)
    assert result.width == 960
    assert result.height == 540
    assert result.source_x == 0
    assert result.source_y == 656
    assert result.source_x2 == 1079
    assert result.source_y2 == 1263


def test_tall_wide_crop_middle_upscale():
    request = {
        "width": 9600,
        "height": 5400,
        "center_x": 0.5,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1080, 1920, **request)
    assert result.width == 1080
    assert result.height == 608
    assert result.source_x == 0
    assert result.source_y == 656
    assert result.source_x2 == 1079
    assert result.source_y2 == 1263


def test_wide_tall_crop_middle_downscale():
    request = {
        "width": 540,
        "height": 960,
        "center_x": 0.5,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 540
    assert result.height == 960
    assert result.source_x == 656
    assert result.source_y == 0
    assert result.source_x2 == 1263
    assert result.source_y2 == 1079


def test_wide_tall_crop_middle_upscale():
    request = {
        "width": 5400,
        "height": 9600,
        "center_x": 0.5,
        "center_y": 0.5,
        "mode": "crop",
    }
    result = plan_scale(1920, 1080, **request)
    assert result.width == 608
    assert result.height == 1080
    assert result.source_x == 656
    assert result.source_y == 0
    assert result.source_x2 == 1263
    assert result.source_y2 == 1079


def test_wide_tall_crop_unspecified_upscale():
    request = {"width": 5400, "height": 9600, "mode": "crop"}
    result = plan_scale(1920, 1080, **request)
    assert result.width == 608
    assert result.height == 1080
    assert result.source_x == 656
    assert result.source_y == 0
    assert result.source_x2 == 1263
    assert result.source_y2 == 1079
