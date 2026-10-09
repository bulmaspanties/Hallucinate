import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "settings"

    Column {
        x: 28; y: 20
        width: parent.width - 56
        spacing: 16

        Text { text: "Settings"; color: Theme.text; font.pixelSize: 30; font.weight: Font.Bold }
        Text { text: "Music folders"; color: Theme.text; font.pixelSize: 20; font.weight: Font.DemiBold }
        Text {
            text: "Folders are scanned in the background and watched for changes."
            color: Theme.textDim; font.pixelSize: 13
        }

        Repeater {
            model: library.folders
            Rectangle {
                required property var modelData
                width: parent.width; height: 48; radius: Theme.radius
                color: Theme.surface
                Text {
                    anchors { left: parent.left; leftMargin: 16; right: rm.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    text: modelData
                    color: Theme.text; font.pixelSize: 14; elide: Text.ElideMiddle
                }
                IconButton {
                    id: rm
                    anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    icon: "close"; size: 14
                    onClicked: library.removeFolder(modelData)
                }
            }
        }

        Row {
            spacing: 10
            TextField {
                id: pathField
                width: 420; height: 38
                placeholderText: "/path/to/music"
                color: Theme.text
                placeholderTextColor: Theme.textDim
                font.pixelSize: 14
                leftPadding: 14
                background: Rectangle { radius: 19; color: Theme.surface; border.color: pathField.activeFocus ? Theme.accent : Theme.border }
                onAccepted: add.clicked()
            }
            PillButton {
                id: add
                primary: true
                text: "Add folder"
                onClicked: { library.addFolder(pathField.text); pathField.text = "" }
            }
            PillButton { text: "Rescan now"; onClicked: library.rescan() }
        }
        Text {
            visible: library.scanning || library.status.length > 0
            text: library.status
            color: Theme.accent; font.pixelSize: 13
        }
    }
}
