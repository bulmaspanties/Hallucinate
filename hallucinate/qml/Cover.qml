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
    // Covers are served by the cached "art" image provider in size buckets, decoded off the GUI thread.
    readonly property real wantedPx: Math.max(width, height) * Screen.devicePixelRatio
    readonly property int bucketPx: wantedPx <= 64 ? 64 : wantedPx <= 128 ? 128 : wantedPx <= 256 ? 256 : 512
    readonly property string sourceText: source.toString()
    readonly property string resolved: sourceText.length === 0 ? ""
        : sourceText.indexOf("file:") === 0 ? "image://art/" + bucketPx + "/" + encodeURIComponent(sourceText)
        : sourceText

    Rectangle {
        anchors.fill: parent
        radius: cover.radius
        color: Theme.surface
    }
    Text {
        anchors.centerIn: parent
        text: cover.fallback
        color: Theme.surfaceHi
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(Math.max(12, cover.width * 0.4))
        visible: img.status !== Image.Ready
    }
    Image {
        id: img
        anchors.fill: parent
        source: cover.resolved
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        opacity: status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
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
