pragma Singleton
import QtQuick

QtObject {
    readonly property color bg: "#0b0b10"
    readonly property color panel: "#12121a"
    readonly property color surface: "#1a1a24"
    readonly property color surfaceHi: "#262633"
    readonly property color border: "#2a2a38"
    readonly property color text: "#f3f3f7"
    readonly property color textDim: "#9b9bad"
    readonly property color accent: "#8f7bff"
    readonly property color accentHi: "#a695ff"
    readonly property int radius: 10
    readonly property int sidebarWidth: 210
    readonly property int playerHeight: 92

    function fmtTime(ms) {
        var s = Math.max(0, Math.floor(ms / 1000))
        var m = Math.floor(s / 60)
        s = s % 60
        return m + ":" + (s < 10 ? "0" : "") + s
    }
}
