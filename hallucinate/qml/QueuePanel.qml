import QtQuick
import QtQuick.Controls
import "."

Rectangle {
    id: panel
    color: Theme.panel

    Row {
        id: head
        x: 18; y: 16
        spacing: 12
        Text { text: "Queue"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(18); font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
        Text { text: player.queueModel.count + " tracks"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); anchors.verticalCenter: parent.verticalCenter }
    }
    Row {
        anchors { right: parent.right; rightMargin: 14; verticalCenter: head.verticalCenter }
        spacing: 8
        PillButton {
            objectName: "saveQueue"
            height: 30
            text: "Save"
            enabled: player.queueModel.count > 0
            onClicked: saveDlg.open()
        }
        PillButton {
            height: 30
            text: "Clear"
            onClicked: player.clearQueue()
        }
    }
    Dialog {
        id: saveDlg
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "Save queue as playlist"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: { saveField.text = ""; saveField.forceActiveFocus() }
        onAccepted: {
            var name = saveField.text.trim()
            if (!name.length) return
            var id = userLib.saveQueueAsPlaylist(name)
            if (id >= 0) Nav.openPlaylist(id)
        }
        TextField { id: saveField; width: 280; placeholderText: "Playlist name"; selectByMouse: true; onAccepted: saveDlg.accept() }
    }
    DropArea {
        id: queueDrop
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: function (drop) {
            if (!drop.hasUrls) return
            library.playDropped(drop.urls, true)
            drop.acceptProposedAction()
        }
        Rectangle {
            anchors.fill: parent
            visible: queueDrop.containsDrag
            color: "transparent"
            border.color: Theme.accent
            border.width: 2
            Text {
                anchors.centerIn: parent
                text: "Drop to add to queue"
                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(16); font.weight: Font.DemiBold
            }
        }
    }
    Text {
        visible: player.queueModel.count === 0
        anchors.centerIn: parent
        text: "Queue is empty"
        color: Theme.textDim
    }
    ListView {
        id: list
        anchors { top: head.bottom; topMargin: 14; left: parent.left; right: parent.right; bottom: parent.bottom }
        anchors.leftMargin: 8; anchors.rightMargin: 4
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: player.queueModel
        currentIndex: player.currentIndex
        ScrollBar.vertical: ScrollBar {}
        onCurrentIndexChanged: if (dragFrom < 0) positionViewAtIndex(currentIndex, ListView.Contain)
        property int dragFrom: -1
        property int dragTo: -1
        property real dragY: 0
        // Auto-scroll while dragging near the top/bottom edge
        Timer {
            interval: 30; repeat: true; running: list.dragFrom >= 0
            onTriggered: {
                var step = list.dragY < 40 ? -12 : (list.dragY > list.height - 40 ? 12 : 0)
                if (step) list.contentY = Math.max(0, Math.min(list.contentHeight - list.height, list.contentY + step))
                if (list.dragFrom >= 0) list.dragTo = Math.max(0, Math.min(list.count - 1, list.indexAt(list.width / 2, list.dragY + list.contentY)))
            }
        }
        Rectangle {
            z: 5; visible: list.dragFrom >= 0 && list.dragTo >= 0 && list.dragTo !== list.dragFrom
            width: list.width - 20; height: 2; color: Theme.accent
            x: 4
            y: list.dragTo * 54 - list.contentY + (list.dragTo > list.dragFrom ? 54 : 0) - 1
        }
        delegate: Rectangle {
            width: ListView.view.width - 10
            height: 54
            radius: Theme.radiusSmall
            color: hh.hovered ? Theme.surface : "transparent"
            HoverHandler { id: hh }
            opacity: ListView.view.dragFrom === index ? 0.4 : 1
            activeFocusOnTab: true
            Keys.onReturnPressed: player.playIndex(index)
            Keys.onPressed: function (e) {
                if ((e.modifiers & Qt.AltModifier) && e.key === Qt.Key_Up && index > 0) { player.moveItem(index, index - 1); e.accepted = true }
                else if ((e.modifiers & Qt.AltModifier) && e.key === Qt.Key_Down && index < ListView.view.count - 1) { player.moveItem(index, index + 1); e.accepted = true }
            }
            Accessible.role: Accessible.ListItem
            Accessible.name: model.title + ", " + model.artist
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: player.playIndex(index) }
            MouseArea {
                id: grip
                width: 22; height: parent.height
                anchors.right: rm.left
                cursorShape: Qt.SizeVerCursor
                preventStealing: true
                function upd(mouse) {
                    var p = mapToItem(list, mouse.x, mouse.y)
                    list.dragY = p.y
                    list.dragTo = Math.max(0, Math.min(list.count - 1, list.indexAt(list.width / 2, p.y + list.contentY)))
                }
                onPressed: function (mouse) { list.dragFrom = index; upd(mouse) }
                onPositionChanged: function (mouse) { if (pressed) upd(mouse) }
                onReleased: {
                    var from = list.dragFrom, to = list.dragTo
                    list.dragFrom = -1; list.dragTo = -1
                    if (from >= 0 && to >= 0 && from !== to) player.moveItem(from, to)
                }
                onCanceled: { list.dragFrom = -1; list.dragTo = -1 }
                Text { anchors.centerIn: parent; text: "⋮⋮"; color: Theme.textDim; opacity: hh.hovered || grip.pressed ? 1 : 0.35; font.pixelSize: 14 }
            }
            Cover { id: art; x: 6; anchors.verticalCenter: parent.verticalCenter; width: 38; height: 38; radius: Theme.radiusSmall; source: model.artUrl }
            Column {
                anchors { left: art.right; leftMargin: 10; right: grip.left; rightMargin: 2; verticalCenter: parent.verticalCenter }
                spacing: 2
                Text {
                    width: parent.width; text: model.title; elide: Text.ElideRight; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                    color: index === player.currentIndex ? Theme.accent : Theme.text
                }
                Text { width: parent.width; text: model.artist; elide: Text.ElideRight; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); color: Theme.textDim }
            }
            IconButton {
                id: rm
                anchors { right: parent.right; rightMargin: 2; verticalCenter: parent.verticalCenter }
                icon: "close"; size: 12
                opacity: hh.hovered ? 1 : 0
                onClicked: player.removeAt(index)
            }
        }
    }
}
