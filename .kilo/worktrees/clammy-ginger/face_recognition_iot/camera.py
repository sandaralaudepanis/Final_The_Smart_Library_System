"""Camera capture helper. Frames are processed in memory and never recorded."""

import cv2

class Camera:
    def __init__(self, device_index=0):
        self.capture = cv2.VideoCapture(device_index)
        if not self.capture.isOpened():
            raise RuntimeError(f"Could not open camera device {device_index}.")

    def read(self):
        success, frame = self.capture.read()
        return frame if success else None

    def close(self):
        self.capture.release()
        cv2.destroyAllWindows()