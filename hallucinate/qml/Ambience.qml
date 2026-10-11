import QtQuick
import QtQuick.Shapes
import "."

// The window backdrop: slow, soft blooms of colour taken from the current cover (or the theme), drifting
// like the clouds in the logo, under a fine film grain. Pure gradients, so it also works without a GPU.
Item {
    id: amb
    property bool animated: true
    property real strength: Theme.light ? 0.26 : 0.55
    clip: true

    Rectangle { anchors.fill: parent; color: Theme.bg }

    component Bloom: Shape {
        id: bloom
        property color tint
        property real size: 600
        property real driftX: 80
        property real driftY: 60
        property int period: 40000
        property real phase: 0
        property real baseX
        property real baseY
        width: size; height: size
        x: baseX - size / 2 + driftX * Math.sin(t * 2 * Math.PI + phase)
        y: baseY - size / 2 + driftY * Math.cos(t * 2 * Math.PI * 0.7 + phase)
        property real t: 0
        NumberAnimation on t { from: 0; to: 1; duration: bloom.period; loops: Animation.Infinite; running: amb.animated && amb.visible }
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: bloom.size / 2; centerY: bloom.size / 2; centerRadius: bloom.size / 2
                focalX: bloom.size / 2; focalY: bloom.size / 2
                GradientStop { position: 0.0; color: Qt.rgba(bloom.tint.r, bloom.tint.g, bloom.tint.b, amb.strength) }
                GradientStop { position: 0.45; color: Qt.rgba(bloom.tint.r, bloom.tint.g, bloom.tint.b, amb.strength * 0.45) }
                GradientStop { position: 1.0; color: Qt.rgba(bloom.tint.r, bloom.tint.g, bloom.tint.b, 0) }
            }
            PathRectangle { x: 0; y: 0; width: bloom.size; height: bloom.size }
        }
    }

    Bloom {
        tint: Theme.art0
        size: Math.max(amb.width, amb.height) * 0.95
        baseX: amb.width * 0.12; baseY: amb.height * 0.05
        period: 47000
    }
    Bloom {
        tint: Theme.art1
        size: Math.max(amb.width, amb.height) * 0.8
        baseX: amb.width * 0.95; baseY: amb.height * 0.45
        driftX: 110; driftY: 70; period: 61000; phase: 1.7
    }
    Bloom {
        tint: Theme.art2
        size: Math.max(amb.width, amb.height) * 0.7
        baseX: amb.width * 0.45; baseY: amb.height * 1.05
        driftX: 140; driftY: 50; period: 73000; phase: 3.1
    }

    // Film grain keeps the gradients from banding and gives the surfaces a printed, tactile feel.
    Image {
        anchors.fill: parent
        source: "../assets/grain.png"
        fillMode: Image.Tile
        opacity: Theme.light ? 0.035 : 0.055
        smooth: false
    }
}
