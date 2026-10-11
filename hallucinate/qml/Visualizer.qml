import QtQuick
import "."

// The music drawn as light, tinted with the current cover's colours. `style` is "liquid", "aurora", "nebula" or
// "bars". Shader styles need a GPU renderer; with Qt's software renderer they fall back to the bars.
// The spectrum comes from player.visualizerLevels (24 bands); without it the shaders keep drifting quietly.
Item {
    id: vis
    property string style: "liquid"
    property bool active: visible
    property real quality: 0.5          // shader resolution relative to the item (they are soft anyway)
    readonly property bool gpu: GraphicsInfo.api !== GraphicsInfo.Software && GraphicsInfo.api !== GraphicsInfo.Unknown
    readonly property bool shaderStyle: style !== "bars" && gpu
    readonly property var levels: player.visualizerLevels || []

    // Smoothed values handed to the shaders: fast attack, slower release, so motion follows the music without jitter
    property real t: 0
    property real bass: 0
    property real mid: 0
    property real treble: 0
    property real energy: 0
    property real beat: 0
    property var bands: new Array(24).fill(0)
    property real _bassAvg: 0

    function avg(from, to) {
        var s = 0, n = 0
        for (var i = from; i < to && i < levels.length; i++) { s += levels[i]; n++ }
        return n ? s / n : 0
    }
    function follow(current, target, dt) {
        var rate = target > current ? 18 : 3.5
        return current + (target - current) * Math.min(1, rate * dt)
    }

    FrameAnimation {
        running: vis.active && vis.shaderStyle
        onTriggered: {
            var dt = Math.min(0.1, frameTime)
            var b = vis.avg(0, 4), m = vis.avg(4, 14), tr = vis.avg(14, 24)
            vis.bass = vis.follow(vis.bass, b, dt)
            vis.mid = vis.follow(vis.mid, m, dt)
            vis.treble = vis.follow(vis.treble, tr, dt)
            vis.energy = vis.follow(vis.energy, (b + m + tr) / 3, dt)
            // a kick: the bass jumps well above its recent average
            vis._bassAvg += (b - vis._bassAvg) * Math.min(1, 1.5 * dt)
            vis.beat = b > vis._bassAvg * 1.35 + 0.08 ? 1 : Math.max(0, vis.beat - 2.5 * dt)
            var next = vis.bands.slice()
            for (var i = 0; i < 24; i++) next[i] = vis.follow(next[i], vis.levels[i] || 0, dt)
            vis.bands = next
            vis.t += dt * (0.6 + 1.4 * vis.energy)
        }
    }

    Item {
        id: canvas
        anchors.fill: parent
        visible: vis.shaderStyle
        layer.enabled: visible
        layer.smooth: true
        layer.textureSize: Qt.size(Math.max(1, width * vis.quality), Math.max(1, height * vis.quality))

        Loader {
            anchors.fill: parent
            active: vis.shaderStyle
            sourceComponent: shaderComponent
        }
    }
    Component {
        id: shaderComponent
        ShaderEffect {
            objectName: "visualizerShader"
            fragmentShader: "shaders/" + vis.style + ".frag.qsb"
            property real time: vis.t
            property real bass: vis.bass
            property real mid: vis.mid
            property real treble: vis.treble
            property real energy: vis.energy
            property real beat: vis.beat
            property size res: Qt.size(canvas.layer.textureSize.width, canvas.layer.textureSize.height)
            property color c0: Theme.art0
            property color c1: Theme.art1
            property color c2: Theme.art2
            property vector4d s0: Qt.vector4d(vis.bands[0], vis.bands[1], vis.bands[2], vis.bands[3])
            property vector4d s1: Qt.vector4d(vis.bands[4], vis.bands[5], vis.bands[6], vis.bands[7])
            property vector4d s2: Qt.vector4d(vis.bands[8], vis.bands[9], vis.bands[10], vis.bands[11])
            property vector4d s3: Qt.vector4d(vis.bands[12], vis.bands[13], vis.bands[14], vis.bands[15])
            property vector4d s4: Qt.vector4d(vis.bands[16], vis.bands[17], vis.bands[18], vis.bands[19])
            property vector4d s5: Qt.vector4d(vis.bands[20], vis.bands[21], vis.bands[22], vis.bands[23])
        }
    }

    // Bars: the style for the software renderer, and a choice of its own
    Row {
        id: bars
        objectName: "visualizerBars"
        visible: !vis.shaderStyle
        anchors { fill: parent; margins: Math.min(48, parent.width * 0.05) }
        spacing: 5
        Repeater {
            model: vis.shaderStyle ? 0 : vis.levels
            Rectangle {
                required property real modelData
                required property int index
                width: Math.max(2, (bars.width - 5 * 23) / 24)
                height: Math.max(4, modelData * (bars.height - 8))
                anchors.bottom: parent.bottom
                radius: Math.min(width / 2, 6)
                gradient: Gradient {
                    GradientStop { position: 0; color: Qt.lighter(Theme.art2, 1.2) }
                    GradientStop { position: 1; color: index % 2 ? Theme.art1 : Theme.art0 }
                }
                opacity: 0.5 + modelData * 0.5
                Behavior on height { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
            }
        }
    }
}
