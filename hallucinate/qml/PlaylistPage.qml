import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "playlist"
    property bool liked: false
    property int playlistId: -1
    property string playlistName: ""
    readonly property var tracksModel: liked ? userLib.likedTracks : userLib.playlistTracks

    Component.onCompleted: if (!liked) userLib.openPlaylist(playlistId)

    Dialog {
        id: renameDlg
        anchors.centerIn: parent
        modal: true
        title: "Rename playlist"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: if (nameField.text.trim().length) { userLib.renamePlaylist(page.playlistId, nameField.text.trim()); page.playlistName = nameField.text.trim() }
        TextField { id: nameField; width: 280; text: page.playlistName; selectByMouse: true; onAccepted: renameDlg.accept() }
    }

    ListView {
        id: list
        anchors.fill: parent
        anchors.leftMargin: 20; anchors.rightMargin: 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: page.tracksModel
        ScrollBar.vertical: ScrollBar {}

        header: Item {
            width: list.width
            height: 150
            Column {
                anchors { left: parent.left; leftMargin: 8; bottom: parent.bottom; bottomMargin: 12 }
                spacing: 8
                Text { text: page.liked ? "COLLECTION" : "PLAYLIST"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.DemiBold }
                Text {
                    text: page.liked ? "Liked Songs" : page.playlistName
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(36)
                    font.weight: Font.Bold
                }
                Text { text: list.count + " songs"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14) }
                Row {
                    spacing: 10
                    PillButton { primary: true; text: "Play"; enabled: list.count > 0; onClicked: page.liked ? userLib.playLiked(0) : userLib.playPlaylist(0, false) }
                    PillButton { text: "Shuffle"; enabled: list.count > 0; onClicked: page.liked ? (player.setShuffle(true), userLib.playLiked(Math.floor(Math.random() * list.count))) : userLib.playPlaylist(0, true) }
                    PillButton { visible: !page.liked; text: "Rename"; onClicked: { nameField.text = page.playlistName; renameDlg.open() } }
                    PillButton { visible: !page.liked; text: "Delete"; onClicked: { userLib.deletePlaylist(page.playlistId); Nav.goHome() } }
                }
            }
        }
        footer: Text {
            visible: list.count === 0
            width: list.width
            height: 120
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: page.liked ? "Tap the heart on any song to add it here." : "Empty playlist. Use “…” on a song to add it."
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(14)
        }
        delegate: TrackRow {
            path: model.path
            rowIndex: index
            context: page.liked ? "liked" : "playlist"
            width: ListView.view.width - 12
            number: index + 1
            title: model.title
            artist: model.artist
            album: model.album
            durText: model.durText
            artUrl: model.artUrl
            current: player.hasTrack && player.current.id === model.id
            onActivated: page.liked ? userLib.playLiked(index) : userLib.playPlaylist(index, false)
            onEnqueue: player.enqueue(page.tracksModel.get(index))
        }
    }
}
