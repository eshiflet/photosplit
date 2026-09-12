# Vendored model

`face_detection_yunet_2023mar.onnx` is the YuNet face detector from the
[OpenCV Zoo](https://github.com/opencv/opencv_zoo), by Shiqi Yu, under the MIT
licence in `LICENSE.yunet`. 227 KB.

It is here rather than downloaded because a scan should not need the network,
and because a photograph turned the wrong way up by a model that failed to load
is worse than one left alone.

It is used for one thing: deciding which way up a photograph goes. Faces are
the only reliable signal for that — a print laid sideways on the glass is
scanned sideways, and nothing in the pixels says which edge was the top.
