import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtCore
import "."

ApplicationWindow {
    id: window
    width: 1280
    height: 800
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    title: player.hasTrack ? player.current.title + " — " + player.current.artist : "Hallucinate"
    color: Theme.bg

    palette.window: Theme.bg
    palette.windowText: Theme.text
    palette.base: Theme.surface
    palette.text: Theme.text
    palette.button: Theme.surface
    palette.buttonText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.onAccent
    palette.placeholderText: Theme.textDim

    property string section: "home"
    property bool queueOpen: false
    property bool lyricsOpen: false
    // A feature switched off while it's showing: leave its page and close its panels
    Connections {
        target: shell
        function onFeaturesChanged() {
            if (!window.featureOn(window.section)) window.go("home")
            if (!window.featureOn("lyrics")) { window.lyricsOpen = false; nowPlaying.lyricsMode = false }
        }
    }
    Connections {  // music servers say how adding and syncing went
        target: servers
        function onMessage(text) { toast.show(text) }
    }

    function pageFor(name) {
        switch (name) {
        case "albums": return albumsPage
        case "artists": return artistsPage
        case "songs": return songsPage
        case "stats": return statsPage
        case "history": return historyPage
        case "health": return healthPage
        case "recap": return recapPage
        case "folders": return foldersPage
        case "visualizer": return visualizerPage
        case "settings": return settingsPage
        case "liked": return likedPage
        case "stations": return stationsPage
        case "podcasts": return podcastsPage
        default: return homePage
        }
    }
    // Browser-style history across every page: Back (the back button, Alt+Left, the mouse's back button) and
    // Forward (Alt+Right, the mouse's forward button) walk through the pages visited, sections included.
    property var route: ({ kind: "section", name: "home" })
    property var backRoutes: []
    property var forwardRoutes: []
    property bool replaying: false
    function sameRoute(a, b) { return a && b && JSON.stringify(a) === JSON.stringify(b) }
    // Where each page was scrolled, by route, so going back to a page (or forward again) lands where you were
    property var scrollMemory: ({})
    function flickOf(item, depth) {
        if (!item || (depth || 0) > 6) return null
        if (item.contentY !== undefined && item.flickableDirection !== undefined && item.contentHeight > item.height)
            return item
        for (var i = 0; i < item.children.length; i++) {
            var f = flickOf(item.children[i], (depth || 0) + 1)
            if (f) return f
        }
        return null
    }
    function saveScroll() {
        var f = flickOf(stack.currentItem)
        if (f) { var m = scrollMemory; m[JSON.stringify(route)] = f.contentY; scrollMemory = m }
    }
    Timer {
        id: restoreScroll
        interval: 80
        onTriggered: {
            var y = window.scrollMemory[JSON.stringify(window.route)]
            var f = window.flickOf(stack.currentItem)
            if (f && y !== undefined) f.contentY = Math.min(y, Math.max(0, f.contentHeight - f.height))
        }
    }
    function remember(next) {
        saveScroll()
        if (!replaying && !sameRoute(route, next)) {
            backRoutes = backRoutes.concat([route]).slice(-100)
            forwardRoutes = []
        }
        route = next
    }
    function routeOf(item, depth) {
        if (!item) return null
        if (item.albumKey !== undefined && item.objectName !== "search" && item.albumKey) return { kind: "album", key: item.albumKey }
        if (item.artistName !== undefined && item.artistName) return { kind: "artist", name: item.artistName }
        if (item.podcastId !== undefined && item.podcastId) return { kind: "podcast", id: item.podcastId }
        return depth === 0 ? route0 : null
    }
    property var route0: ({ kind: "section", name: "home" })  // what sits at the bottom of the page stack
    function visit(r) {
        replaying = true
        if (r.kind === "section") go(r.name)
        else if (r.kind === "playlist") openPlaylist(r.id, r.name)
        else if (r.kind === "smart") openSmartPlaylist(r.id, r.name)
        else if (r.kind === "album") openAlbum(r.key)
        else if (r.kind === "artist") openArtist(r.name)
        else if (r.kind === "podcast") openPodcast(r.id)
        route = r
        replaying = false
    }
    function goBack() {
        if (stack.currentItem && stack.currentItem.objectName === "search") { searchField.text = ""; return }
        if (!backRoutes.length) return
        var target = backRoutes[backRoutes.length - 1]
        backRoutes = backRoutes.slice(0, -1)
        forwardRoutes = forwardRoutes.concat([route])
        if (stack.depth > 1 && sameRoute(routeOf(stack.get(stack.depth - 2), stack.depth - 2), target)) {
            stack.pop()  // the page is still there underneath, scrolled where it was
            route = target
        } else visit(target)
    }
    function forgetRoute(kind, id) {  // a deleted playlist or unfollowed show: Back and Forward skip it
        var keep = function (r) { return !(r.kind === kind && r.id === id) }
        backRoutes = backRoutes.filter(keep)
        forwardRoutes = forwardRoutes.filter(keep)
    }
    function goForward() {
        if (!forwardRoutes.length) return
        var target = forwardRoutes[forwardRoutes.length - 1]
        forwardRoutes = forwardRoutes.slice(0, -1)
        backRoutes = backRoutes.concat([route])
        visit(target)
    }

    // For tests and tools: an item by objectName anywhere in the window (Repeater rows included), and the
    // names of the visible ones that start with `prefix`.
    function findItem(name, root) {
        root = root || window.contentItem
        if (root.objectName === name) return root
        for (var i = 0; i < root.children.length; i++) {
            var found = findItem(name, root.children[i])
            if (found) return found
        }
        return null
    }
    function visibleNames(prefix, root) {
        root = root || window.contentItem
        if (!root.visible) return []
        var out = root.objectName.indexOf(prefix) === 0 ? [root.objectName] : []
        for (var i = 0; i < root.children.length; i++) out = out.concat(visibleNames(prefix, root.children[i]))
        return out
    }
    function visibleTexts(root) {
        // Every visible piece of text, for tests; the Features switches themselves are left out.
        root = root || window.contentItem
        if (!root.visible || root.opacity === 0 || root.objectName.indexOf("feature_") === 0) return []
        var out = typeof root.text === "string" && root.text.length ? [root.text] : []
        for (var i = 0; i < root.children.length; i++) out = out.concat(visibleTexts(root.children[i]))
        return out
    }
    function pastTheEdge(root, clipped) {
        // For tests: visible, unclipped things that reach past the window's right edge (2 px: the outline).
        root = root || window.contentItem
        if (!root.visible || root.opacity === 0) return []
        var out = []
        var cls = root.toString()
        var plain = cls.indexOf("QQuickItem") === 0 || cls.indexOf("QQuickRepeater") === 0
        if (!clipped && root.width > 0 && root.height > 0 && !plain) {
            var box = root.mapToItem(null, 0, 0, root.width, root.height)
            if (box.x + box.width > window.width + 3 && box.x < window.width)
                out.push((root.objectName || cls.split("_QML")[0].split("(")[0])
                         + (typeof root.text === "string" && root.text ? " “" + root.text + "”" : "")
                         + " reaches x=" + Math.round(box.x + box.width))
        }
        if (root.clip || /^QQuick(ListView|GridView|Flickable|PopupItem)/.test(cls)) clipped = true
        for (var i = 0; i < root.children.length; i++) out = out.concat(pastTheEdge(root.children[i], clipped))
        return out
    }
    function searchText() { return searchField.text }
    function featureOn(name) { return shell.features[name] !== false }  // pages that aren't features are always on
    function go(name) {
        if (!featureOn(name)) name = "home"
        remember({ kind: "section", name: name })
        route0 = route
        section = name
        stack.clear()
        stack.push(pageFor(name))
        if (searchField.text.length > 0) searchField.text = ""
    }
    function openPlaylist(id, name) {
        remember({ kind: "playlist", id: id, name: name })
        route0 = route
        section = "pl" + id
        stack.clear()
        stack.push(playlistPage, { playlistId: id, playlistName: name })
        if (searchField.text.length > 0) searchField.text = ""
    }
    function openSmartPlaylist(id, name) {
        remember({ kind: "smart", id: id, name: name })
        route0 = route
        section = "smart" + id
        stack.clear()
        stack.push(smartPlaylistPage, { smartId: id, playlistName: name })
        if (searchField.text.length > 0) searchField.text = ""
    }
    function newPlaylist() { createDlg.open() }
    function openAlbum(key) { remember({ kind: "album", key: key }); stack.push(albumDetail, { albumKey: key }) }
    function openArtist(name) { remember({ kind: "artist", name: name }); stack.push(artistDetail, { artistName: name }) }
    function openPodcast(id) {
        if (!featureOn("podcasts")) return
        if (section !== "podcasts") go("podcasts")
        remember({ kind: "podcast", id: id })
        stack.push(podcastDetail, { podcastId: id })
    }
    function showSearch() {
        if (stack.currentItem && stack.currentItem.objectName === "search") return
        stack.push(searchPage, { query: searchField.text })
    }

    Component { id: homePage; HomePage {} }
    Component { id: albumsPage; AlbumsPage {} }
    Component { id: artistsPage; ArtistsPage {} }
    Component { id: songsPage; SongsPage {} }
    Component { id: statsPage; StatsPage {} }
    Component { id: historyPage; HistoryPage {} }
    Component { id: healthPage; HealthPage {} }
    Component { id: recapPage; RecapPage {} }
    Component { id: foldersPage; FoldersPage {} }
    Component { id: visualizerPage; VisualizerPage {} }
    Component { id: settingsPage; SettingsPage {} }
    Component { id: likedPage; PlaylistPage { liked: true } }
    Component { id: stationsPage; StationsPage {} }
    Component { id: podcastsPage; PodcastsPage {} }
    Component { id: podcastDetail; PodcastPage {} }
    Component { id: playlistPage; PlaylistPage {} }
    Component { id: smartPlaylistPage; SmartPlaylistPage {} }
    Component { id: searchPage; SearchPage {} }
    Component { id: albumDetail; AlbumDetailPage {} }
    Component { id: artistDetail; ArtistDetailPage {} }

    Connections {
        target: Nav
        function onOpenAlbum(key) { window.openAlbum(key) }
        function onOpenArtist(name) { window.openArtist(name) }
        function onOpenPodcast(id) { window.openPodcast(id) }
        function onGoToPlaying() {
            if (!player.hasTrack) return
            var c = player.current
            if (c.kind === "station") window.go("stations")
            else if (c.kind === "episode") window.openPodcast(c.podcast_id)
            else if (c.album_key) window.openAlbum(c.album_key)
        }
        function onOpenSettings() { window.go("settings") }
        function onOpenLiked() { window.go("liked") }
        function onGoHome() { window.go("home") }
        function onOpenHistory(day) {
            if (!window.featureOn("history")) return
            window.go("history")
            if (day.length && stack.currentItem) stack.currentItem.period = "day:" + day
        }
        function onOpenPlaylist(id) {
            var name = ""
            for (var i = 0; i < userLib.playlists.count; i++) if (userLib.playlists.get(i).id === id) name = userLib.playlists.get(i).name
            window.openPlaylist(id, name)
        }
        function onOpenSmartPlaylist(id, name) { window.openSmartPlaylist(id, name) }
        function onEditSmartPlaylist(id, name) { smartEditor.openEdit(id, name) }
        function onEditTags(path) { tagEditor.editTrack(path) }
        function onEditAlbum(key) { tagEditor.editAlbum(key) }
        function onSearch(text) { searchField.text = text; searchField.forceActiveFocus() }
        function onFindAlbumGenre(key) { tagEditor.editAlbum(key); if (tagEditor.albumKey === key) tagEditor.findGenre() }
        function onEditTagsMany(paths) { tagEditor.editTracks(paths) }
        function onArtistMenu(name) { if (name) collectionMenu.showArtist(name) }
        function onFolderMenu(path, name) { if (path) collectionMenu.showFolder(path, name) }
        function onTrackMenu(path, title, context, index) {
            // on a song that's part of a selection, the menu acts on the whole selection
            if (Selection.count > 1 && Selection.paths.indexOf(path) >= 0) trackMenu.showMany(Selection.paths)
            else trackMenu.show(path, title, context, index)
        }
        function onToggleNowPlaying() { nowPlaying.toggle() }
        function onOpenHealth() { if (window.featureOn("health")) window.go("health") }
        function onOpenPalette() { commandPalette.show() }
        function onNewSmartPlaylist() { smartEditor.openNew() }
        function onImportPlaylist() { importDialog.open() }
        function onExportPlaylist(kind, name) {
            exportDialog.kind = kind
            exportDialog.selectedFile = StandardPaths.writableLocation(StandardPaths.MusicLocation) + "/"
                                        + (name || "Playlist").replace(/[\\/:*?"<>|#%]/g, "-") + ".m3u8"
            exportDialog.open()
        }
        function onNotify(message) { toast.show(message) }
        function onNotifyAction(message, actionText, action) { toast.show(message, 0, actionText, action) }
        function onBack() { window.goBack() }
        function onRouteGone(kind, id) { window.forgetRoute(kind, id) }
        function onInstallUpdate() { updateDlg.open() }
        function onAlbumMenu(keys, title, artist) {
            // acting on a selected album acts on the whole selection
            var k = keys.length === 1 && AlbumSelection.has(keys[0]) ? AlbumSelection.keys.slice() : keys
            albumMenu.show(k, title, artist)
        }
        function onRemoveAlbums(keys, what) { removeDlg.songs = false; removeDlg.keys = keys; removeDlg.what = what; removeDlg.open() }
        function onTrashAlbums(keys, what) { trashDlg.songs = false; trashDlg.keys = keys; trashDlg.what = what; trashDlg.open() }
        function onRemoveSongs(paths, what) { removeDlg.songs = true; removeDlg.keys = paths; removeDlg.what = what; removeDlg.open() }
        function onTrashSongs(paths, what) {
            trashDlg.songs = true; trashDlg.keys = paths; trashDlg.what = what
            trashDlg.cue = paths.some(p => /\.[A-Za-z0-9]+#\d+$/.test(p))
            trashDlg.open()
        }
    }

    Timer {
        id: searchTimer
        interval: 120
        onTriggered: {
            library.search(searchField.text)
            if (searchField.text.length > 0) {
                window.showSearch()
                if (stack.currentItem) stack.currentItem.query = searchField.text
            } else if (stack.currentItem && stack.currentItem.objectName === "search") {
                stack.pop()  // back to the page the search was typed over
            }
        }
    }

    TrackMenu { id: trackMenu; objectName: "trackMenu" }
    AlbumMenu { id: albumMenu }
    CollectionMenu { id: collectionMenu }
    CommandPalette { id: commandPalette; win: window }

    // Playlist files
    FileDialog {
        id: importDialog
        title: "Import a playlist"
        nameFilters: ["Playlists (*.m3u *.m3u8 *.pls)", "All files (*)"]
        onAccepted: userLib.importPlaylist(selectedFile.toString())
    }
    FileDialog {
        id: exportDialog
        property string kind: "playlist"
        title: "Export as a playlist file"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "m3u8"
        nameFilters: ["M3U8 playlist (*.m3u8)", "M3U playlist (*.m3u)"]
        onAccepted: {
            var err = userLib.exportPlaylist(kind, selectedFile.toString())
            toast.show(err.length ? err : "Playlist saved")
        }
    }
    Connections {
        target: userLib
        function onPlayerImported(result) {
            if (result.error) { toast.show(result.error); return }
            toast.show(result.source + ": matched " + result.matched + " of " + result.songs + " songs · "
                       + result.plays + " plays, " + result.ratings + " ratings, " + result.playlists + " playlists")
        }
        function onPlaylistImported(result) {
            if (result.error) { toast.show(result.error); return }
            if (result.id < 0) { toast.show("None of those songs are in your library"); return }
            toast.show("Imported “" + result.name + "”: " + result.added + (result.added === 1 ? " song" : " songs")
                       + (result.missing ? ", " + result.missing + " not found in your library" : ""))
            window.openPlaylist(result.id, result.name)
        }
    }

    // Acts on songs selected with Ctrl/Shift+click; a selection belongs to one page
    SelectionBar {
        z: 59
        // over the page area (right of the sidebar), never wider than it
        maxWidth: stack.width - 24
        x: sidebar.width + (stack.width - width) / 2
        anchors { bottom: parent.bottom; bottomMargin: 112 }
        onEditTags: function (paths) { tagEditor.editTracks(paths) }
    }
    AlbumBar {
        z: 59
        maxWidth: stack.width - 24
        x: sidebar.width + (stack.width - width) / 2
        anchors { bottom: parent.bottom; bottomMargin: 112 }
    }
    onSectionChanged: { Selection.clear(); AlbumSelection.clear() }
    Connections { target: stack; function onCurrentItemChanged() { Selection.clear(); AlbumSelection.clear() } }
    // One Escape for both kinds of selection: two shortcuts on the same key at once would be ambiguous, and Qt
    // then runs neither. Selecting songs drops a selection of albums and the other way round, so their bars
    // never sit on top of each other.
    Shortcut {
        sequence: "Escape"
        enabled: (Selection.count > 0 || AlbumSelection.count > 0) && !nowPlaying.open
        onActivated: { Selection.clear(); AlbumSelection.clear() }
    }
    Connections { target: Selection; function onCountChanged() { if (Selection.count > 0) AlbumSelection.clear() } }
    Connections { target: AlbumSelection; function onCountChanged() { if (AlbumSelection.count > 0) Selection.clear() } }

    ConfirmDialog {
        id: removeFolderDlg
        objectName: "removeFolderDialog"
        property string path: ""
        title: "Remove this music folder?"
        confirmText: "Remove"
        body: "“" + path + "” and the songs in it leave the library. The files stay on your disk; add the folder "
              + "again to bring them back (a full rescan). If it's on a drive that's only unplugged, plug it back in instead."
        onAccepted: library.removeFolder(path)
    }
    Connections {
        target: Nav
        function onRemoveFolder(path) { removeFolderDlg.path = path; removeFolderDlg.open() }
    }

    // Removing albums: from the library only (files stay; Settings → Library brings them back), or to the trash
    ConfirmDialog {
        id: removeDlg
        objectName: "removeAlbumsDialog"
        title: "Remove from the library?"
        confirmText: "Remove"
        body: what + ": the music stays on your disk; Hallucinate just stops showing it, and rescans leave it out. "
              + "Settings → Library can bring it back. Plays, likes and playlists are kept."
        property bool songs: false  // keys are song paths rather than album keys
        onAccepted: {
            if (songs) { library.removeSongs(keys); Selection.clear() }
            else { library.removeAlbums(keys); AlbumSelection.clear() }
        }
    }
    ConfirmDialog {
        id: trashDlg
        objectName: "trashAlbumsDialog"
        title: "Move to the trash?"
        confirmText: "Move to trash"
        destructive: true
        body: what + ": the music files go to your system's trash, where you can restore them from. A folder left with only "
              + "covers or logs goes too; anything else in it stays."
              + (cue ? " Songs from a CUE sheet share one audio file with the rest of their album, so that whole file goes." : "")
        property bool songs: false
        property bool cue: false  // a CUE sheet's songs share one file: trashing one trashes the whole sheet's audio
        onAccepted: {
            if (songs) { library.trashSongs(keys); Selection.clear() }
            else { library.trashAlbums(keys); AlbumSelection.clear() }
        }
    }
    Connections {
        target: library
        function onAlbumsRemoved(r) {
            var n = r.albums > 0 ? r.albums + (r.albums === 1 ? " album" : " albums")
                                 : r.songs + (r.songs === 1 ? " song" : " songs")
            if (r.kind === "hidden") toast.show(n + " removed from the library", 0, "Undo",
                                                function () { library.unhidePaths(r.paths || []) })
            else if (r.failed && !r.songs) toast.show("Couldn't move the files to the trash")
            else toast.show(n + " moved to the trash" + (r.failed ? " (" + r.failed + " files couldn't be moved)" : ""))
            if (r.songs > 0 && stack.currentItem && r.keys.indexOf(stack.currentItem.albumKey) >= 0) {
                window.goBack()  // its page is gone, so it can't be gone forward to either
                window.forwardRoutes = window.forwardRoutes.slice(0, -1)
            }
        }
    }

    Connections {
        target: userLib
        function onLovesMatched(n) { toast.show(n ? "Liked " + n + (n === 1 ? " song" : " songs") + " you'd loved on Last.fm" : "No new songs to like from your Last.fm loves") }
    }
    Connections {
        target: stations
        function onUndoable(text) { toast.show(text, 0, "Undo", function () { stations.undo() }) }
    }
    Connections {
        target: podcasts
        function onUndoable(text) { toast.show(text, 0, "Undo", function () { podcasts.undo() }) }
    }
    // A short message at the bottom of the window
    Rectangle {
        id: toast
        objectName: "toast"
        property string message: ""
        property string actionText: ""
        property var action: null
        // `actionText` and `action` (a function) add a button, such as Undo; the toast then stays a little longer
        function show(text, ms, actionText, action) {
            message = text
            toast.actionText = action ? (actionText || "Undo") : ""
            toast.action = action || null
            opacity = 1
            toastTimer.interval = ms || (action ? 8000 : 4500)
            toastTimer.restart()
        }
        z: 60
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: Selection.count > 0 || AlbumSelection.count > 0 ? 176 : 118 }
        width: toastText.width + 36 + (toastAction.visible ? toastAction.width + 14 : 0)
        height: Math.max(40, toastText.height + 22)
        radius: 20
        color: Theme.glassStrong
        border.width: 1
        border.color: Theme.strokeHi
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Text {
            textFormat: Text.PlainText
            id: toastAction
            objectName: "toastAction"
            visible: toast.actionText.length > 0
            anchors { right: parent.right; rightMargin: 18; verticalCenter: parent.verticalCenter }
            text: toast.actionText
            color: actionMouse.containsMouse ? Theme.accentHi : Theme.accent
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.Bold
            LinkArea {
                id: actionMouse
                name: toast.actionText
                hoverEnabled: true
                onClicked: { var f = toast.action; toast.action = null; toast.actionText = ""; toast.opacity = 0; if (f) f() }
            }
        }
        Text {
            textFormat: Text.PlainText
            id: toastText
            anchors.centerIn: toastAction.visible ? undefined : parent
            x: toastAction.visible ? 18 : (parent.width - width) / 2
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, Math.max(200, window.width - 260))  // long messages wrap
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            text: toast.message
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
        }
        Timer { id: toastTimer; interval: 4500; onTriggered: toast.opacity = 0 }
    }
    // e.g. a damaged library database that was restored from its backup at start-up
    Timer { interval: 800; running: shell.startupNotice.length > 0; onTriggered: toast.show(shell.startupNotice, 15000) }
    // The previous run crashed or hit an error: offer its report once, for a bug report
    ConfirmDialog {
        id: crashDlg
        objectName: "crashDialog"
        readonly property bool froze: !shell.lastRunCrashed && shell.crashReport.indexOf("Stopped responding:") === 0
        title: shell.lastRunCrashed ? "Hallucinate closed unexpectedly"
               : froze ? "Hallucinate stopped responding" : "Hallucinate ran into an error"
        confirmText: "Copy report"
        body: (shell.lastRunCrashed ? "Last time, Hallucinate closed unexpectedly."
               : froze ? "Last time, Hallucinate's window stopped responding for a while."
               : "Last time, Hallucinate hit an error it couldn't handle.")
              + " A report of what happened is ready: paste it into a bug report so it can be fixed. It describes your setup"
              + " and the error, without file paths, names or anything from your library."
        Component.onCompleted: { var b = standardButton(Dialog.Cancel); if (b) b.text = "Not now" }
        onAccepted: { shell.copyCrashReport(); toast.show("Report copied — paste it into a bug report", 6000) }
        onRejected: shell.dismissCrashReport()
    }
    Timer { interval: 900; running: shell.crashReport.length > 0 && !crashDlg.opened; onTriggered: crashDlg.open() }
    // Once after an update: what's new in this version
    Dialog {
        id: whatsNewDlg
        objectName: "whatsNewDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(520, window.width - 40)
        modal: true
        title: "New in Hallucinate " + shell.appVersion
        standardButtons: Dialog.Ok
        onClosed: shell.dismissWhatsNew()
        Flickable {
            implicitHeight: Math.min(whatsNewCol.height, window.height - 200)
            width: whatsNewDlg.availableWidth
            contentHeight: whatsNewCol.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            Column {
                id: whatsNewCol
                width: whatsNewDlg.availableWidth - 10
                spacing: 10
                Repeater {
                    model: shell.whatsNew
                    Row {
                        required property string modelData
                        width: parent.width
                        spacing: 10
                        Rectangle { width: 6; height: 6; radius: 3; color: Theme.accent; y: 7 }
                        Text {
                            textFormat: Text.PlainText
                            width: parent.width - 16
                            wrapMode: Text.WordWrap
                            text: modelData
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                        }
                    }
                }
                Text {
                    textFormat: Text.PlainText
                    text: "Everything that changed"
                    color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); font.weight: Font.DemiBold
                    LinkArea { onClicked: Qt.openUrlExternally("https://github.com/Phosphene-dev/Hallucinate/releases") }
                }
            }
        }
    }
    Timer {
        interval: 1200
        running: shell.whatsNew.length > 0 && !crashDlg.opened && shell.crashReport.length === 0
        onTriggered: whatsNewDlg.open()
    }
    SmartPlaylistEditor {
        id: smartEditor
        onSaved: function (id, name) { window.openSmartPlaylist(id, name) }
    }
    TagEditor { id: tagEditor; objectName: "tagEditor" }
    MiniPlayer {}
    onClosing: function (close) {
        var result = shell.handleClose()
        close.accepted = result === "quit"
        if (result === "ask") closeDlg.open()
    }
    // Asked on close until a choice is remembered (Settings → Desktop changes it later)
    Dialog {
        id: closeDlg
        objectName: "closeDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 440
        modal: true
        title: "Close Hallucinate?"
        function choose(action) {
            if (rememberClose.checked) shell.setCloseAction(action)
            closeDlg.close()
            shell.closeWith(action)
        }
        Column {
            width: closeDlg.availableWidth
            spacing: 14
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: shell.canMinimize && shell.trayAvailable && shell.trayEnabled
                      ? "Quit, or keep the music going with the window minimized or tucked away in the tray?"
                      : shell.canMinimize ? "Quit, or keep the music going with the window minimized?"
                                          : "Quit, or keep the music going with the window tucked away in the tray?"
                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            StyledCheck { id: rememberClose; text: "Remember my choice"; checked: false }
            Flow {
                width: parent.width
                spacing: 8
                PillButton { objectName: "closeQuit"; text: "Quit"; primary: true; onClicked: closeDlg.choose("quit") }
                PillButton { objectName: "closeMinimize"; visible: shell.canMinimize; text: "Minimize"; onClicked: closeDlg.choose("minimize") }
                PillButton {
                    objectName: "closeTray"
                    visible: shell.trayAvailable && shell.trayEnabled
                    text: "Keep playing in the tray"
                    onClicked: closeDlg.choose("tray")
                }
                PillButton { text: "Cancel"; onClicked: closeDlg.close() }
            }
        }
        onOpened: rememberClose.checked = false
    }
    Dialog {
        id: createDlg
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "New playlist"
        standardButtons: Dialog.Ok | Dialog.Cancel
        onOpened: { createField.text = ""; createField.forceActiveFocus() }
        onAccepted: if (createField.text.trim().length) window.openPlaylist(userLib.createPlaylist(createField.text.trim()), createField.text.trim())
        TextField {
            id: createField; width: 280; placeholderText: "Playlist name"; selectByMouse: true
            onAccepted: if (text.trim().length) createDlg.accept()  // no nameless playlists
            onTextChanged: { var b = createDlg.standardButton(Dialog.Ok); if (b) b.enabled = text.trim().length > 0 }
            onVisibleChanged: if (visible) { var b = createDlg.standardButton(Dialog.Ok); if (b) b.enabled = text.trim().length > 0 }
        }
    }

    Dialog {
        id: updateDlg
        objectName: "updateDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 420
        modal: true
        title: "Update to Hallucinate " + Theme.plain(shell.updates.latestVersion) + "?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        Component.onCompleted: { var b = standardButton(Dialog.Ok); if (b) b.text = "Update now" }
        onAccepted: shell.updates.installNow()
        Text {
            textFormat: Text.PlainText
            width: updateDlg.availableWidth
            wrapMode: Text.WordWrap
            text: "Hallucinate downloads the new version from GitHub, checks it against the release's checksum, "
                  + "then closes and reopens to finish. Your library, playlists and settings stay as they are."
                  + (Qt.platform.os === "windows" ? " Windows may ask for permission to install." : "")
            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
        }
    }

    // Drop audio files or folders anywhere to play them (the queue panel, above it, appends instead)
    DropArea {
        id: dropArea
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: function (drop) {
            if (!drop.hasUrls) return
            library.playDropped(drop.urls, false)
            drop.acceptProposedAction()
        }
    }

    Ambience {
        objectName: "ambience"
        anchors.fill: parent
        z: -1
        animated: shell.ambientMotion && !shell.reduceMotion && window.active && !nowPlaying.covering
        visible: !nowPlaying.covering
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        visible: !nowPlaying.covering  // nothing to draw under Now Playing

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Sidebar {
                id: sidebar
                Layout.preferredWidth: width
                Layout.fillHeight: true
                section: window.section
                atRoot: stack.depth <= 1
                onNavigate: id => window.go(id)
                onOpenPlaylist: (id, name) => window.openPlaylist(id, name)
                onOpenSmartPlaylist: (id, name) => window.openSmartPlaylist(id, name)
                onNewPlaylist: window.newPlaylist()
                onNewSmartPlaylist: smartEditor.openNew()
                onRearrange: { window.go("settings"); Qt.callLater(function () { var p = stack.currentItem; if (p && p.jumpToSidebar) p.jumpToSidebar() }) }
            }

            // Content
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    IconButton {
                        id: backBtn
                        anchors { left: parent.left; leftMargin: 18; verticalCenter: parent.verticalCenter }
                        icon: "back"
                        visible: window.backRoutes.length > 0 || (stack.currentItem && stack.currentItem.objectName === "search")
                        tip: "Back (Alt+Left)"
                        onClicked: Nav.back()
                    }
                    TextField {
                        id: searchField
                        objectName: "searchField"
                        anchors { left: backBtn.visible ? backBtn.right : parent.left; leftMargin: backBtn.visible ? 8 : 24; verticalCenter: parent.verticalCenter }
                        width: Math.min(520, parent.width - 120)
                        height: 42
                        placeholderText: "Search   ( / )        Ctrl+K  commands & pages"
                        placeholderTextColor: Theme.textDim
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                        leftPadding: 44
                        rightPadding: 14
                        selectByMouse: true
                        background: Rectangle {
                            radius: height / 2
                            color: searchField.activeFocus ? Theme.glassStrong : Theme.glass
                            border.width: 1
                            border.color: searchField.activeFocus ? Theme.strokeHi : Theme.stroke
                            Behavior on border.color { ColorAnimation { duration: 160 } }
                            Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; width: 16; height: 16; name: "search"; color: searchField.activeFocus ? Theme.accentHi : Theme.textDim }
                        }
                        onTextChanged: searchTimer.restart()
                        Keys.onEscapePressed: { text = ""; focus = false; window.contentItem.forceActiveFocus() }
                        Keys.onReturnPressed: if (stack.currentItem && stack.currentItem.objectName === "search") window.contentItem.forceActiveFocus()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0
                    StackView {
                        id: stack
                        objectName: "pageStack"
                        onCurrentItemChanged: restoreScroll.restart()
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        // Pages dissolve in with a slight rise: soft, not a hard cut
                        pushEnter: Theme.reduceMotion ? null : fadeIn
                        pushExit: Theme.reduceMotion ? null : fadeOut
                        Transition {
                            id: fadeIn
                            ParallelAnimation {
                                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 220; easing.type: Easing.OutCubic }
                                NumberAnimation { property: "y"; from: 14; to: 0; duration: 260; easing.type: Easing.OutCubic }
                            }
                        }
                        Transition { id: fadeOut; NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 120 } }
                        popEnter: pushEnter
                        popExit: pushExit
                        replaceEnter: pushEnter
                        replaceExit: pushExit
                    }
                    QueuePanel {
                        Layout.preferredWidth: window.queueOpen ? 330 : 0
                        Layout.fillHeight: true
                        Layout.rightMargin: 10
                        Layout.bottomMargin: 4
                        visible: window.queueOpen
                    }
                    LyricsPanel {
                        Layout.preferredWidth: window.lyricsOpen ? 350 : 0
                        Layout.fillHeight: true
                        Layout.rightMargin: 10
                        Layout.bottomMargin: 4
                        visible: window.lyricsOpen
                    }
                }
            }
        }

        NowPlayingBar {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.playerHeight
            Layout.margins: 10
            Layout.topMargin: 6
            queueOpen: window.queueOpen
            lyricsOpen: window.lyricsOpen
            onToggleQueue: { window.queueOpen = !window.queueOpen; if (window.queueOpen) window.lyricsOpen = false }
            onToggleLyrics: { window.lyricsOpen = !window.lyricsOpen; if (window.lyricsOpen) window.queueOpen = false }
        }
    }

    // Keyboard shortcuts (disabled while typing in the search box)
    // Any text field with the focus (the search, a page's filter, a dialog's field): the window's single-key
    // shortcuts (Space, arrows, letters) stand aside so the keys reach it.
    readonly property bool typing: searchField.activeFocus
        || (window.activeFocusItem !== null && window.activeFocusItem.cursorPosition !== undefined)
    // A focused Qt control (a checkbox, a combo box, a dialog's buttons) presses itself with Space
    readonly property bool onControl: window.activeFocusItem !== null && window.activeFocusItem.down !== undefined
    Shortcut { sequence: "Space"; enabled: !window.typing && !window.onControl; onActivated: player.toggle() }
    Shortcut { sequence: "Left"; enabled: !window.typing; onActivated: player.seekBy(-5000) }
    Shortcut { sequence: "Right"; enabled: !window.typing; onActivated: player.seekBy(5000) }
    Shortcut { sequence: "Up"; enabled: !window.typing; onActivated: player.changeVolume(0.05) }
    Shortcut { sequence: "Down"; enabled: !window.typing; onActivated: player.changeVolume(-0.05) }
    Shortcut { sequence: "N"; enabled: !window.typing; onActivated: player.next() }
    Shortcut { sequence: "P"; enabled: !window.typing; onActivated: player.previous() }
    Shortcut { sequence: "S"; enabled: !window.typing; onActivated: player.toggleShuffle() }
    Shortcut { sequence: "R"; enabled: !window.typing; onActivated: player.cycleRepeat() }
    Shortcut { sequence: "Q"; enabled: !window.typing; onActivated: { window.queueOpen = !window.queueOpen; if (window.queueOpen) window.lyricsOpen = false } }
    Shortcut { sequence: "Ctrl+M"; onActivated: shell.toggleMini() }
    Shortcut {
        sequence: "Ctrl+Z"
        enabled: !window.typing && player.canUndoQueue
        onActivated: { var what = player.undoQueue(); if (what) toast.show("Undone: " + what.toLowerCase()) }
    }
    Repeater {
        model: 6  // Ctrl+1…5 rates the playing song, Ctrl+0 clears it
        Item {
            required property int index
            Shortcut {
                sequence: "Ctrl+" + index
                enabled: player.hasTrack && !(player.current.kind || "").length  // stations and episodes have no rating
                onActivated: userLib.setRating(player.current.path, index === 0 ? userLib.rating(player.current.path) : index)
            }
        }
    }
    Shortcut { sequence: "F"; enabled: !window.typing; onActivated: nowPlaying.toggle() }
    Shortcut { sequence: "Escape"; enabled: nowPlaying.open; onActivated: nowPlaying.open = false }
    Shortcut { sequence: "F11"; onActivated: nowPlaying.toggleFullScreen() }
    Shortcut {
        sequence: "L"; enabled: !window.typing && window.featureOn("lyrics")
        onActivated: {
            if (nowPlaying.open) { nowPlaying.lyricsMode = !nowPlaying.lyricsMode; return }
            window.lyricsOpen = !window.lyricsOpen; if (window.lyricsOpen) window.queueOpen = false
        }
    }
    Shortcut { sequence: "Alt+Left"; onActivated: Nav.back() }
    Shortcut { sequence: "Alt+Right"; onActivated: window.goForward() }
    // The mouse's back and forward side buttons, anywhere in the window; other buttons pass straight through
    MouseArea {
        anchors.fill: parent
        z: 1000
        acceptedButtons: Qt.BackButton | Qt.ForwardButton
        Accessible.role: Accessible.Pane
        Accessible.name: "Hallucinate"
        onClicked: function (mouse) { mouse.button === Qt.BackButton ? Nav.back() : window.goForward() }
    }
    Shortcut { sequences: ["Ctrl+K", "Ctrl+P"]; onActivated: commandPalette.opened ? commandPalette.close() : commandPalette.show() }
    Shortcut { sequences: ["/", "Ctrl+F"]; enabled: !window.typing; onActivated: { searchField.forceActiveFocus(); searchField.selectAll() } }
    Shortcut { sequence: "Ctrl+Q"; onActivated: Qt.quit() }

    NowPlayingView { id: nowPlaying; anchors.fill: parent }
    Welcome { anchors.fill: parent; onFinished: window.go("home") }

    Rectangle {
        anchors.fill: parent
        visible: dropArea.containsDrag
        color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.8)
        border.color: Theme.accent
        border.width: 3
        Text {
            textFormat: Text.PlainText
            anchors.centerIn: parent
            text: "Drop to play"
            color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(21); font.weight: Font.DemiBold
        }
    }

    Component.onCompleted: go("home")
}
