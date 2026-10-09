pragma Singleton
import QtQuick

QtObject {
    readonly property color bg: themeManager.bg
    readonly property color panel: themeManager.panel
    readonly property color surface: themeManager.surface
    readonly property color surfaceHi: themeManager.surfaceHi
    readonly property color border: themeManager.border
    readonly property color text: themeManager.text
    readonly property color textDim: themeManager.textDim
    readonly property color accent: themeManager.accent
    readonly property color accentHi: themeManager.accentHi
    readonly property color error: themeManager.error
    readonly property color onAccent: themeManager.onAccent
    readonly property string fontFamily: themeManager.fontFamily
    readonly property real fontScale: themeManager.fontScale
    readonly property int radius: themeManager.radius
    readonly property real radiusSmall: Math.max(2, radius * 0.6)
    readonly property real radiusLarge: radius * 2
    readonly property int sidebarWidth: themeManager.sidebarWidth
    readonly property int playerHeight: themeManager.playerHeight

    function fontSize(pixels) { return pixels * fontScale }

    function fmtTime(ms) {
        var s = Math.max(0, Math.floor(ms / 1000))
        var m = Math.floor(s / 60)
        s = s % 60
        return m + ":" + (s < 10 ? "0" : "") + s
    }
}
