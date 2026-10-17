import QtQuick
import QtQuick.Controls
import "."

// Right-click (or "…") on a song anywhere: play and queue it, playlists, its album, artist and folder, tags,
// and taking it out of the library or moving it to the trash. Opened on a song that is part of a selection, it
// acts on the whole selection (and leaves out what only makes sense for one song).
Menu {
    id: menu
    objectName: "trackMenu"
    property string path: ""
    property string trackTitle: ""
    property string context: ""
    property int index: -1
    property var info: ({})
    property var paths: []
    readonly property bool single: paths.length <= 1
    // a radio station or a streamed episode: no tags, ratings, playlists or files to act on
    readonly property bool stream: paths.some(function (p) { return /^https?:\/\//.test(p) || podcasts.isEpisode(p) })
    // a song on a music server: no file here to show, edit or put in the trash
    readonly property bool onServer: paths.some(function (p) { return /^(subsonic|jellyfin):\/\//.test(p) })
    readonly property string what: single ? "“" + trackTitle + "”" : paths.length + " songs"

    function show(p, t, c, i) {
        path = p; trackTitle = t; context = c; index = i; paths = [p]
        info = /^https?:\/\//.test(p) || podcasts.isEpisode(p) ? ({}) : library.trackInfo(p)
        popup()
    }
    function showMany(list) {
        paths = list.slice(); path = list[0]; trackTitle = ""; context = ""; index = -1
        info = ({})
        popup()
    }
    function done(message) { if (!single) Selection.clear(); if (message) Nav.notify(message) }

    Item {
        objectName: "menuRating"
        visible: menu.single && !menu.stream
        width: 220; height: visible ? 38 : 0
        Text {
            textFormat: Text.PlainText
            x: 14
            anchors.verticalCenter: parent.verticalCenter
            text: "Rating"
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
        }
        StarRating {
            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
            path: menu.path
            size: 17
        }
    }
    MenuSeparator { visible: menu.single && !menu.stream; height: visible ? implicitHeight : 0 }
    MenuItem {
        objectName: "trackCopyLink"
        visible: menu.stream && menu.single && /^https?:\/\//.test(menu.path)
        height: visible ? implicitHeight : 0
        text: "Copy stream link"; icon.name: "playlist"
        onTriggered: { shell.copyText(menu.path); Nav.notify("Stream link copied") }
    }
    MenuItem {
        visible: !menu.stream; height: visible ? implicitHeight : 0
        text: "Play"; icon.name: "play"; onTriggered: { userLib.playPaths(menu.paths); menu.done("") }
    }
    MenuItem {
        visible: !menu.stream; height: visible ? implicitHeight : 0
        text: "Play next"; icon.name: "next"
        onTriggered: { userLib.playNextPaths(menu.paths); menu.done(menu.single ? "" : menu.what + " will play next") }
    }
    MenuItem {
        visible: !menu.stream; height: visible ? implicitHeight : 0
        text: "Add to queue"; icon.name: "queue"
        onTriggered: { userLib.enqueuePaths(menu.paths); menu.done(menu.what + " added to the queue") }
    }
    MenuItem {
        readonly property bool liked: userLib.likesRevision >= 0 && userLib.allLiked(menu.paths)
        visible: !menu.stream && shell.features.liked !== false; height: visible ? implicitHeight : 0
        text: liked ? "Remove from Liked Songs" : "Add to Liked Songs"
        icon.name: "heart"
        onTriggered: { userLib.setLikedPaths(menu.paths, !liked); menu.done("") }
    }
    Menu {
        id: plMenu
        title: "Add to playlist"
        icon.name: "playlist"
        enabled: !menu.stream
        MenuItem { text: "New playlist…"; icon.name: "plus"; onTriggered: newDlg.open() }
        MenuSeparator {}
        Instantiator {
            model: userLib.playlists
            delegate: MenuItem {
                required property int id
                required property string name
                text: Theme.plain(name)
                onTriggered: { userLib.addPathsToPlaylist(id, menu.paths); menu.done(menu.what + " added to “" + name + "”") }
            }
            onObjectAdded: (i, o) => plMenu.addItem(o)
            onObjectRemoved: (i, o) => plMenu.removeItem(o)
        }
    }
    MenuSeparator { visible: !menu.stream; height: visible ? implicitHeight : 0 }
    MenuItem {
        visible: menu.single && (menu.info.album_key || "").length > 0 && menu.context !== "album"
        height: visible ? implicitHeight : 0
        text: "Go to album"
        icon.name: "album"
        onTriggered: Nav.openAlbum(menu.info.album_key)
    }
    MenuItem {
        visible: menu.single && (menu.info.album_artist || menu.info.artist || "").length > 0 && menu.context !== "artist"
        height: visible ? implicitHeight : 0
        text: "Go to " + Theme.plain(menu.info.album_artist || menu.info.artist || "")
        icon.name: "artist"
        onTriggered: Nav.openArtist(menu.info.album_artist || menu.info.artist)
    }
    MenuItem {
        objectName: "trackShowInFolder"
        visible: menu.single && !menu.stream && !menu.onServer
        height: visible ? implicitHeight : 0
        enabled: menu.info.exists === true
        text: "Show in folder"
        icon.name: "folder"
        onTriggered: library.showInFolder(menu.path)
    }
    MenuItem {
        visible: !menu.stream; height: visible ? implicitHeight : 0
        text: "Edit tags…"
        icon.name: "edit"
        // CUE sheet songs are edited in the .cue file, and a server's songs on the server
        enabled: !menu.onServer && menu.paths.every(function (p) { return !/\.[A-Za-z0-9]+#\d+$/.test(p) })
        onTriggered: menu.single ? Nav.editTags(menu.path) : Nav.editTagsMany(menu.paths)
    }
    MenuItem {
        objectName: "trackRemoveFromQueue"
        visible: menu.single && menu.context === "queue"
        height: visible ? implicitHeight : 0
        text: "Remove from the queue"
        icon.name: "close"
        onTriggered: { player.removeAt(menu.index); Nav.notifyAction("Removed from the queue", "Undo", function () { player.undoQueue() }) }
    }
    MenuItem {
        visible: menu.single && menu.context === "playlist"
        height: visible ? implicitHeight : 0
        text: "Remove from this playlist"
        icon.name: "remove"
        icon.color: Theme.error
        onTriggered: userLib.removeFromPlaylist(menu.index)
    }
    MenuSeparator { visible: !menu.stream; height: visible ? implicitHeight : 0 }
    MenuItem {
        objectName: "trackRemove"
        visible: !menu.stream; height: visible ? implicitHeight : 0
        text: "Remove from library…"; icon.name: "remove"; icon.color: Theme.error
        onTriggered: Nav.removeSongs(menu.paths, menu.what)
    }
    MenuItem {
        objectName: "trackTrash"
        visible: !menu.stream && !menu.onServer; height: visible ? implicitHeight : 0
        text: "Move to trash…"; icon.name: "trash"; icon.color: Theme.error
        enabled: !menu.single || menu.info.exists === true
        onTriggered: Nav.trashSongs(menu.paths, menu.what)
    }

    Dialog {
        id: newDlg
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "New playlist"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: { nf.text = ""; nf.forceActiveFocus() }
        onAccepted: if (nf.text.trim().length) { Nav.openPlaylist(userLib.addPathsToNewPlaylist(nf.text.trim(), menu.paths)); menu.done("") }
        TextField {
            id: nf; width: 280; placeholderText: "Playlist name"; selectByMouse: true
            onAccepted: if (text.trim().length) newDlg.accept()  // no nameless playlists
            onTextChanged: { var b = newDlg.standardButton(Dialog.Ok); if (b) b.enabled = text.trim().length > 0 }
            onVisibleChanged: if (visible) { var b = newDlg.standardButton(Dialog.Ok); if (b) b.enabled = text.trim().length > 0 }
        }
    }
}
