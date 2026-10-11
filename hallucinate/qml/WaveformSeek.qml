import QtQuick
import QtQuick.Controls
import "."

// The seek bar: the track's own loudness drawn as the logo's waveform bars. The played part is lit; hover
// shows the time under the pointer; click or drag to seek. A flat line stands in while the track is analysed.
Item {
    id: seek
    objectName: "waveformSeek"
    property var peaks: player.waveform
    property real position: player.position
    property real duration: Math.max(1, player.duration)
    property bool interactive: player.hasTrack
    readonly property int barWidth: 3
    readonly property int gap: 2
    readonly property int bars: Math.max(8, Math.floor((width + gap) / (barWidth + gap)))
    readonly property bool hasPeaks: peaks && peaks.length > 0
    readonly property real shown: drag.pressed ? drag.ratio : position / duration
    implicitHeight: 30

    // Peaks resampled to one value per bar (the loudest in each group, so short hits survive)
    readonly property var levels: {
        var out = []
        if (!hasPeaks) return out
        var n = peaks.length
        for (var b = 0; b < bars; b++) {
            var from = Math.floor(b * n / bars), to = Math.max(from + 1, Math.floor((b + 1) * n / bars))
            var m = 0
            for (var i = from; i < to; i++) m = Math.max(m, peaks[i])
            out.push(m)
        }
        return out
    }
    onLevelsChanged: { dim.requestPaint(); lit.requestPaint() }
    onWidthChanged: { dim.requestPaint(); lit.requestPaint() }
    onHeightChanged: { dim.requestPaint(); lit.requestPaint() }

    function paintBars(ctx, w, h, color) {
        ctx.reset()
        ctx.fillStyle = color
        for (var b = 0; b < seek.bars; b++) {
            var level = seek.hasPeaks ? seek.levels[b] : 0
            var bh = Math.max(2, Math.round(level * (h - 2)))
            var x = b * (seek.barWidth + seek.gap)
            ctx.beginPath()
            ctx.roundedRect(x, (h - bh) / 2, seek.barWidth, bh, 1.5, 1.5)
            ctx.fill()
        }
    }

    Canvas {
        id: dim
        anchors.fill: parent
        opacity: seek.hasPeaks ? 1 : 0.6
        onPaint: seek.paintBars(getContext("2d"), width, height, Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, Theme.light ? 0.22 : 0.18))
    }
    Item {
        id: litClip
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        width: Math.max(0, Math.min(1, seek.shown)) * seek.width
        clip: true
        Canvas {
            id: lit
            width: seek.width; height: seek.height
            onPaint: {
                var ctx = getContext("2d")
                var grad = ctx.createLinearGradient(0, 0, width, 0)
                grad.addColorStop(0, Theme.accentHi)
                grad.addColorStop(1, Qt.tint(Theme.accent, Qt.rgba(Theme.art1.r, Theme.art1.g, Theme.art1.b, 0.5)))
                seek.paintBars(ctx, width, height, grad)
            }
        }
    }
    Connections {
        target: Theme
        function onAccentChanged() { dim.requestPaint(); lit.requestPaint() }
        function onArt1Changed() { lit.requestPaint() }
    }

    // Playhead
    Rectangle {
        visible: seek.interactive
        x: Math.round(litClip.width) - 1
        anchors.verticalCenter: parent.verticalCenter
        width: 2; height: parent.height + 4; radius: 1
        color: Theme.text
        opacity: hover.hovered || drag.pressed ? 0.95 : 0.55
    }

    // Hover position and time
    Rectangle {
        visible: hover.hovered && seek.interactive && !drag.pressed
        x: hover.point.position.x
        width: 1; height: parent.height
        color: Theme.text
        opacity: 0.35
    }
    ToolTip {
        visible: seek.interactive && (hover.hovered || drag.pressed)
        x: (drag.pressed ? drag.ratio * seek.width : hover.point.position.x) - width / 2
        y: -height - 6
        text: Theme.fmtTime((drag.pressed ? drag.ratio : hover.point.position.x / Math.max(1, seek.width)) * seek.duration)
    }
    HoverHandler { id: hover; enabled: seek.interactive }

    MouseArea {
        id: drag
        anchors.fill: parent
        anchors.topMargin: -6; anchors.bottomMargin: -6
        enabled: seek.interactive
        cursorShape: Qt.PointingHandCursor
        property real ratio: 0
        function update(mx) { ratio = Math.max(0, Math.min(1, mx / Math.max(1, seek.width))) }
        onPressed: mouse => update(mouse.x)
        onPositionChanged: mouse => { if (pressed) update(mouse.x) }
        onReleased: player.seek(ratio * seek.duration)
    }
    Accessible.role: Accessible.Slider
    Accessible.name: "Seek"
}
