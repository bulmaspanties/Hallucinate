import QtQuick
import QtQuick.Effects
import "."

Rectangle {
    id: cover
    property url source
    property string fallback: "♪"
    color: "transparent"
    // Shader masking is unavailable with the software renderer; fall back to square corners.
    readonly property bool useMask: GraphicsInfo.api !== GraphicsInfo.Software

    Rectangle {
        anchors.fill: parent
        radius: cover.radius
        color: Theme.surface
    }
    Text {
        anchors.centerIn: parent
        text: cover.fallback
        color: Theme.surfaceHi
        font.pixelSize: Math.max(12, cover.width * 0.4)
        visible: img.status !== Image.Ready
    }
    Image {
        id: img
        anchors.fill: parent
        source: cover.source
        sourceSize.width: 320
        sourceSize.height: 320
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        visible: !cover.useMask
        layer.enabled: cover.useMask
    }
    Rectangle {
        id: mask
        anchors.fill: parent
        radius: cover.radius
        visible: false
        layer.enabled: cover.useMask
    }
    MultiEffect {
        anchors.fill: parent
        source: img
        maskEnabled: true
        maskSource: mask
        visible: cover.useMask && img.status === Image.Ready
    }
}
