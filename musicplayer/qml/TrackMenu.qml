import QtQuick
import QtQuick.Controls
import "."

Menu {
    id: menu
    property string path: ""
    property string trackTitle: ""
    property string context: ""
    property int index: -1

    function show(p, t, c, i) { path = p; trackTitle = t; context = c; index = i; popup() }

    MenuItem { text: "Play next"; onTriggered: userLib.playNextPath(menu.path) }
    MenuItem { text: "Add to queue"; onTriggered: userLib.enqueuePath(menu.path) }
    MenuItem {
        text: userLib.likesRevision >= 0 && userLib.isLiked(menu.path) ? "Remove from Liked Songs" : "Add to Liked Songs"
        onTriggered: userLib.toggleLike(menu.path)
    }
    Menu {
        id: plMenu
        title: "Add to playlist"
        MenuItem { text: "New playlist…"; onTriggered: newDlg.open() }
        MenuSeparator {}
        Instantiator {
            model: userLib.playlists
            delegate: MenuItem {
                required property int id
                required property string name
                text: name
                onTriggered: userLib.addToPlaylist(id, menu.path)
            }
            onObjectAdded: (i, o) => plMenu.addItem(o)
            onObjectRemoved: (i, o) => plMenu.removeItem(o)
        }
    }
    MenuItem {
        visible: menu.context === "playlist"
        height: visible ? implicitHeight : 0
        text: "Remove from this playlist"
        onTriggered: userLib.removeFromPlaylist(menu.index)
    }

    Dialog {
        id: newDlg
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "New playlist"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: { nf.text = ""; nf.forceActiveFocus() }
        onAccepted: if (nf.text.trim().length) { var id = userLib.addToNewPlaylist(nf.text.trim(), menu.path); Nav.openPlaylist(id) }
        TextField { id: nf; width: 280; placeholderText: "Playlist name"; selectByMouse: true; onAccepted: newDlg.accept() }
    }
}
