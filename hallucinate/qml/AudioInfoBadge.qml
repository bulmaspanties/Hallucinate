import QtQuick
import QtQuick.Controls
import "."

Item {
    id: badge
    property string formatName: ""
    property int bitrate: 0
    readonly property string bitrateText: bitrate > 0 ? "~" + Math.round(bitrate / 1000) + " kb/s" : ""
    readonly property string label: {
        var format = formatName.trim().toUpperCase()
        if (bitrateText.length)
            return (format.length ? format + " · " : "") + bitrateText
        return format
    }
    readonly property string spokenLabel: {
        var format = formatName.trim().toUpperCase()
        if (bitrate > 0)
            return (format.length ? format + " audio, " : "Audio, ") +
                   "approximately " + Math.round(bitrate / 1000) + " kilobits per second"
        return format.length ? format + " audio, bitrate unavailable" : "Audio bitrate unavailable"
    }
    implicitWidth: labelText.implicitWidth + 14
    implicitHeight: 18
    width: implicitWidth
    height: implicitHeight
    visible: label.length > 0
    Accessible.role: Accessible.StaticText
    Accessible.name: spokenLabel

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Theme.surface
        border.width: 1
        border.color: Theme.border
    }
    Text {
        id: labelText
        anchors.centerIn: parent
        text: badge.label
        color: Theme.textDim
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(10)
    }
    HoverHandler { id: hover }
    ToolTip.visible: hover.hovered
    ToolTip.text: spokenLabel
}
