from autox.selector import Selector

# submit bounds [100,200][300,280] -> center (200,240), min(w,h)=80.


def test_gesture_builds_two_strokes(fake_device):
    fake_device.gestures = []
    Selector(fake_device, {"resourceId": "com.app:id/submit"}).gesture((10, 10), (20, 20), (30, 30), (40, 40))
    strokes, _ = fake_device.gestures[-1]
    assert strokes == [(10, 10, 30, 30), (20, 20, 40, 40)]  # finger1 s→e, finger2 s→e


def test_pinch_out_fingers_move_apart(fake_device):
    fake_device.gestures = []
    Selector(fake_device, {"resourceId": "com.app:id/submit"}).pinch_out(percent=80)
    strokes, _ = fake_device.gestures[-1]
    (ax1, ay1, ax2, ay2), (bx1, by1, bx2, by2) = strokes
    assert ax1 > ax2 and bx1 < bx2  # A moves left, B moves right (apart)
    assert ay1 == ay2 == 240 and by1 == by2 == 240  # along the element's mid-line


def test_pinch_in_fingers_move_together(fake_device):
    fake_device.gestures = []
    Selector(fake_device, {"resourceId": "com.app:id/submit"}).pinch_in(percent=80)
    strokes, _ = fake_device.gestures[-1]
    (ax1, _, ax2, _), (bx1, _, bx2, _) = strokes
    assert ax1 < ax2 and bx1 > bx2  # A moves right, B moves left (together)
