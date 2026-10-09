pragma Singleton
import QtQuick

QtObject {
    id: root
    // Colors cross-fade on theme and album-accent changes.
    readonly property int duration: 220
    // Values are plain properties (not bindings) so ColorAnimations can cross-fade them.
    Component.onCompleted: {
        bg = themeManager.bg
        panel = themeManager.panel
        surface = themeManager.surface
        surfaceHi = themeManager.surfaceHi
        border = themeManager.border
        text = themeManager.text
        textDim = themeManager.textDim
        accent = themeManager.accent
        accentHi = themeManager.accentHi
        error = themeManager.error
        onAccent = themeManager.onAccent
    }
    property list<QtObject> fades: [
        ColorAnimation { id: fade_bg; target: root; property: "bg"; duration: root.duration },
        ColorAnimation { id: fade_panel; target: root; property: "panel"; duration: root.duration },
        ColorAnimation { id: fade_surface; target: root; property: "surface"; duration: root.duration },
        ColorAnimation { id: fade_surfaceHi; target: root; property: "surfaceHi"; duration: root.duration },
        ColorAnimation { id: fade_border; target: root; property: "border"; duration: root.duration },
        ColorAnimation { id: fade_text; target: root; property: "text"; duration: root.duration },
        ColorAnimation { id: fade_textDim; target: root; property: "textDim"; duration: root.duration },
        ColorAnimation { id: fade_accent; target: root; property: "accent"; duration: root.duration },
        ColorAnimation { id: fade_accentHi; target: root; property: "accentHi"; duration: root.duration },
        ColorAnimation { id: fade_error; target: root; property: "error"; duration: root.duration },
        ColorAnimation { id: fade_onAccent; target: root; property: "onAccent"; duration: root.duration }
    ]
    property Connections watcher: Connections {
        target: themeManager
        function onThemeChanged() {
            fade_bg.stop(); fade_bg.to = themeManager.bg; fade_bg.start()
            fade_panel.stop(); fade_panel.to = themeManager.panel; fade_panel.start()
            fade_surface.stop(); fade_surface.to = themeManager.surface; fade_surface.start()
            fade_surfaceHi.stop(); fade_surfaceHi.to = themeManager.surfaceHi; fade_surfaceHi.start()
            fade_border.stop(); fade_border.to = themeManager.border; fade_border.start()
            fade_text.stop(); fade_text.to = themeManager.text; fade_text.start()
            fade_textDim.stop(); fade_textDim.to = themeManager.textDim; fade_textDim.start()
            fade_accent.stop(); fade_accent.to = themeManager.accent; fade_accent.start()
            fade_accentHi.stop(); fade_accentHi.to = themeManager.accentHi; fade_accentHi.start()
            fade_error.stop(); fade_error.to = themeManager.error; fade_error.start()
            fade_onAccent.stop(); fade_onAccent.to = themeManager.onAccent; fade_onAccent.start()
        }
    }
    property color bg: themeManager.bg
    property color panel: themeManager.panel
    property color surface: themeManager.surface
    property color surfaceHi: themeManager.surfaceHi
    property color border: themeManager.border
    property color text: themeManager.text
    property color textDim: themeManager.textDim
    property color accent: themeManager.accent
    property color accentHi: themeManager.accentHi
    property color error: themeManager.error
    property color onAccent: themeManager.onAccent
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
