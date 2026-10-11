import QtQuick
import QtQuick.Controls
import "."

// The signal path: a small pill saying whether the sound reaches the output untouched; click it for every
// stage from file to device, with the ones that change the sound lit.
Item {
    id: sp
    objectName: "signalPath"
    readonly property var path: player.signalPath || ({})
    readonly property var stages: path.stages || []
    property bool light: false   // white text, for dark backdrops like Now Playing
    implicitWidth: pill.width
    implicitHeight: 20
    visible: stages.length > 0

    Rectangle {
        id: pill
        height: 20
        width: pillRow.implicitWidth + 16
        radius: 10
        color: sp.path.untouched ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16) : "transparent"
        border.width: 1
        border.color: sp.path.untouched ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.55)
                                        : (sp.light ? Qt.rgba(1, 1, 1, 0.25) : Theme.stroke)
        Row {
            id: pillRow
            anchors.centerIn: parent
            spacing: 5
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 6; height: 6; radius: 3
                color: sp.path.untouched ? Theme.accent : (sp.light ? Qt.rgba(1, 1, 1, 0.6) : Theme.textDim)
            }
            Text {
                text: sp.path.untouched ? "Untouched" : "Processed"
                color: sp.path.untouched ? (sp.light ? "white" : Theme.accent) : (sp.light ? Qt.rgba(1, 1, 1, 0.75) : Theme.textDim)
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(10)
                font.weight: Font.DemiBold
            }
        }
        MouseArea {
            id: pillMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: popup.opened ? popup.close() : popup.open()
        }
        ToolTip.visible: pillMouse.containsMouse && !popup.opened
        ToolTip.text: (sp.path.summary || "") + " — click for the signal path"
        ToolTip.delay: 500
        Accessible.role: Accessible.Button
        Accessible.name: "Signal path: " + (sp.path.summary || "")
    }

    Popup {
        id: popup
        objectName: "signalPathPopup"
        y: -height - 10
        x: Math.min(0, -width / 2 + pill.width / 2)
        width: 330
        padding: 18
        margins: 10
        background: Rectangle {
            radius: 18
            color: Theme.glassStrong
            border.width: 1
            border.color: Theme.stroke
        }
        contentItem: Column {
            spacing: 0
            Text {
                text: "Signal path"
                color: Theme.text
                font.family: Theme.displayFamily
                font.pixelSize: Theme.fontSize(15)
                font.weight: Font.DemiBold
                bottomPadding: 4
            }
            Text {
                width: 294
                text: sp.path.untouched
                    ? "Nothing between the file and the output changes the sound."
                    : (sp.path.summary || "") + "."
                color: sp.path.untouched ? Theme.accent : Theme.textDim
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                bottomPadding: 12
            }
            Repeater {
                model: sp.stages
                Item {
                    required property var modelData
                    required property int index
                    width: 294
                    height: 42
                    // the line joining the stages
                    Rectangle {
                        x: 5; width: 2
                        y: index === 0 ? 21 : 0
                        height: index === sp.stages.length - 1 ? 21 : parent.height - (index === 0 ? 21 : 0)
                        color: Theme.stroke
                    }
                    Rectangle {
                        x: 0; y: 15; width: 12; height: 12; radius: 6
                        color: modelData.active ? Theme.accent : Theme.surface
                        border.width: 2
                        border.color: modelData.active ? Theme.accentHi : Theme.stroke
                    }
                    Column {
                        x: 24; y: 5
                        width: parent.width - 24
                        Text {
                            text: modelData.name
                            color: Theme.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(12)
                            font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width
                            text: modelData.detail
                            color: modelData.active ? Theme.accent : Theme.textDim
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSize(11)
                        }
                    }
                }
            }
        }
    }
}
