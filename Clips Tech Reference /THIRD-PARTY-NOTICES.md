# Third-party notices

## stop-slop (writing-style rules)

Source: https://github.com/hvpandya/stop-slop — its writing rules are
adapted and condensed into `references/style-rules/core.md` (the original
essay files are not shipped).

MIT License

Copyright (c) 2025 Hardik Pandya

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Montserrat (font, shipped in assets/)

Copyright 2011 The Montserrat Project Authors
(https://github.com/JulietaUla/Montserrat)

Licensed under the SIL Open Font License, Version 1.1 — the complete license
text ships beside the font at `assets/OFL.txt`.

## YuNet face-detection model (downloaded at runtime, not shipped)

The layout probe fetches `face_detection_yunet_2023mar.onnx` (~230KB) once
from the official OpenCV Zoo repository
(https://github.com/opencv/opencv_zoo) into `~/.perfect-clips/models/`.
The OpenCV Zoo is licensed Apache License 2.0; the YuNet model is provided
by its authors for detection use. The model file itself never ships inside
this package.
