# Linux audio backend notes

Hallucinate currently uses Qt Multimedia's normal audio-output path. Playback
goes to the system's default output device unless another one is chosen in
Settings → Playback (a chosen device that is unplugged falls back to the default
until it returns); when an equalizer is enabled, decoded PCM passes through a Qt
audio sink on the same device. This works with the Linux audio stack provided
by the installed Qt build, including PipeWire systems exposing their normal
desktop audio devices.

The application does not open a native PipeWire stream, request exclusive
access, or promise bit-perfect output. Qt's public `QAudioOutput` /
`QAudioSink` APIs expose device selection, but not PipeWire-specific exclusive
stream flags or direct hardware-format negotiation. Therefore exclusive output
is not available in the current player. The equalizer necessarily processes
PCM and should be disabled for any future bit-perfect mode.

Relevant upstream references:

- [QMediaDevices](https://doc.qt.io/qt-6/qmediadevices.html) documents Qt
  audio-device enumeration and selection.
- [Qt Multimedia Linux platform notes](https://doc.qt.io/qt-6/qtmultimedia-platform-notes-linux.html)
  describe Qt's Linux backend requirements and routing.

Implementing native PipeWire stream controls would require a separate backend
or a Qt integration that exposes PipeWire properties. It should be optional,
with Qt Multimedia remaining the portable default, and needs real-device
verification across PipeWire versions and desktop environments.
