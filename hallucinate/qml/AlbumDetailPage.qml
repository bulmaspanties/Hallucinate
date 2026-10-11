import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import "."

// An album as a sleeve: the cover large, lit by its own colours, with liner notes (genre, format, discs, size,
// when it arrived and how you've listened to it) and the tracks split by disc.
Item {
    id: page
    objectName: "album"
    property string albumKey
    readonly property var info: library.albumInfo(albumKey)
    readonly property var tracks: library.albumTracksModel(albumKey)
    readonly property var notes: library.albumNotes(albumKey)
    readonly property var coverColors: library.albumPalette(albumKey)
    readonly property color glow0: coverColors.length > 0 ? coverColors[0] : Theme.accent
    readonly property color glow1: coverColors.length > 1 ? coverColors[1] : Theme.art1
    readonly property bool multiDisc: (notes.discs || 0) > 1

    function fmtDate(ts) { return ts > 0 ? Qt.formatDate(new Date(ts * 1000), "d MMM yyyy") : "" }
    function formatLine() {
        var parts = []
        if ((notes.formats || []).length) parts.push(notes.formats.join(" / "))
        if ((notes.sampleRates || []).length) {
            var r = notes.sampleRates.map(function (x) { return (x / 1000).toFixed(x % 1000 ? 1 : 0) })
            parts.push(r.join(" / ") + " kHz")
        }
        if (!notes.lossless && notes.bitrate > 0) parts.push(Math.round(notes.bitrate / 1000) + " kbps")
        return parts.join("  ·  ")
    }
    function listening() {
        if (!notes.plays) return "Not played yet"
        var s = notes.plays + (notes.plays === 1 ? " play" : " plays")
        if (notes.firstPlayed) s += "  ·  first " + fmtDate(notes.firstPlayed)
        if (notes.lastPlayed) s += "  ·  last " + fmtDate(notes.lastPlayed)
        return s
    }

    // The album's own colours, blooming behind the sleeve
    component Bloom: Shape {
        id: bloom
        property color tint
        property real size: 700
        width: size; height: size
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: 0; strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: bloom.size / 2; centerY: bloom.size / 2; centerRadius: bloom.size / 2
                focalX: bloom.size / 2; focalY: bloom.size / 2
                GradientStop { position: 0; color: Qt.rgba(bloom.tint.r, bloom.tint.g, bloom.tint.b, Theme.light ? 0.22 : 0.32) }
                GradientStop { position: 1; color: Qt.rgba(bloom.tint.r, bloom.tint.g, bloom.tint.b, 0) }
            }
            PathRectangle { x: 0; y: 0; width: bloom.size; height: bloom.size }
        }
    }

    component Note: Column {
        property string label
        property string value
        visible: value.length > 0
        spacing: 3
        width: Math.min(implicitWidth, 320)
        Text {
            text: parent.label.toUpperCase()
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(10)
            font.weight: Font.DemiBold
            font.letterSpacing: 1.2
        }
        Text {
            text: parent.value
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
            elide: Text.ElideRight
            width: Math.min(implicitWidth, 320)
        }
    }

    ListView {
        id: list
        anchors.fill: parent
        anchors.leftMargin: 20; anchors.rightMargin: 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: page.tracks
        ScrollBar.vertical: ScrollBar {}

        header: Item {
            width: list.width
            height: sleeve.height + notesPanel.height + 70

            Bloom { tint: page.glow0; x: sleeve.x + sleeve.width / 2 - size / 2; y: sleeve.y + sleeve.height / 2 - size / 2 }
            Bloom { tint: page.glow1; size: 520; x: sleeve.x + sleeve.width * 1.6 - size / 2; y: sleeve.y - size / 3 }

            Item {
                id: sleeve
                x: 8; y: 24
                width: Math.min(300, list.width * 0.32); height: width
                Repeater {  // soft shadow from stacked outlines (no effects needed)
                    model: 6
                    Rectangle {
                        required property int index
                        anchors { fill: parent; margins: -(index + 1) * 3; topMargin: -(index + 1) * 3 + 8 }
                        radius: 18 + (index + 1) * 3
                        color: "transparent"
                        border.width: 3
                        border.color: Qt.rgba(0, 0, 0, (Theme.light ? 0.06 : 0.12) - index * 0.015)
                    }
                }
                Cover {
                    objectName: "albumSleeve"
                    anchors.fill: parent
                    radius: 18
                    source: page.info.artUrl || ""
                    fallback: (page.info.album || "?").charAt(0)
                }
            }
            Column {
                anchors { left: sleeve.right; leftMargin: 30; right: parent.right; rightMargin: 20; bottom: sleeve.bottom }
                spacing: 8
                Text {
                    text: "ALBUM"
                    color: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(11)
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.6
                }
                Text {
                    width: parent.width
                    text: page.info.album || ""
                    color: Theme.text
                    font.family: Theme.displayFamily
                    font.pixelSize: Theme.fontSize(page.info.album && page.info.album.length > 28 ? 26 : 34)
                    font.weight: Font.Bold
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                Row {
                    spacing: 6
                    Text {
                        text: page.info.album_artist || ""
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(16)
                        font.weight: Font.DemiBold
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Nav.openArtist(page.info.album_artist)
                        }
                    }
                    Text {
                        text: "·  " + (page.info.year > 0 ? page.info.year + "  ·  " : "") + page.info.n
                              + (page.info.n === 1 ? " song" : " songs") + "  ·  " + page.info.durText
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                    }
                }
                Row {
                    spacing: 10
                    topPadding: 10
                    PillButton {
                        objectName: "playAlbum"
                        primary: true
                        text: "Play"
                        onClicked: { player.setShuffle(false); player.playList(page.tracks.toList(), 0) }
                    }
                    PillButton {
                        text: "Shuffle"
                        onClicked: {
                            player.setShuffle(true)
                            player.playList(page.tracks.toList(), Math.floor(Math.random() * page.tracks.count))
                        }
                    }
                    PillButton { text: "Add to queue"; onClicked: player.enqueueAll(page.tracks.toList()) }
                    PillButton { text: "Edit"; onClicked: Nav.editAlbum(page.albumKey) }
                }
            }

            // Liner notes
            GlassPanel {
                id: notesPanel
                objectName: "linerNotes"
                anchors { left: parent.left; right: parent.right; rightMargin: 20; top: sleeve.bottom; topMargin: 26 }
                height: notesFlow.implicitHeight + 36
                Flow {
                    id: notesFlow
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
                    spacing: 32
                    Note { label: "Genre"; value: (page.notes.genres || []).join(", ") }
                    Note { label: "Format"; value: page.formatLine() + (page.notes.lossless ? "  ·  lossless" : "") }
                    Note { label: "Discs"; value: page.multiDisc ? String(page.notes.discs) : "" }
                    Note { label: "Size"; value: page.notes.bytes ? Theme.fmtBytes(page.notes.bytes) : "" }
                    Note { label: "Added"; value: page.fmtDate(page.notes.added || 0) }
                    Note { objectName: "albumListening"; label: "Your listening"; value: page.listening() }
                    Note { label: "Liked"; value: page.notes.liked ? page.notes.liked + (page.notes.liked === 1 ? " song" : " songs") : "" }
                }
            }
        }

        section.property: page.multiDisc ? "disc_no" : ""
        section.delegate: Item {
            readonly property string disc: section
            width: list.width
            height: 46
            Text {
                x: 12
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 8
                text: "Disc " + parent.disc
                color: Theme.text
                font.family: Theme.displayFamily
                font.pixelSize: Theme.fontSize(15)
                font.weight: Font.DemiBold
            }
        }

        delegate: TrackRow {
            path: model.path
            audioFormat: model.codec
            audioBitrate: model.bitrate
            rowIndex: index
            width: ListView.view.width - 12
            number: model.track_no > 0 ? model.track_no : index + 1
            title: model.title
            artist: model.artist
            durText: model.durText
            showArt: false
            showAlbum: false
            current: player.hasTrack && player.current.id === model.id
            onActivated: player.playList(page.tracks.toList(), index)
            onEnqueue: player.enqueue(page.tracks.get(index))
        }
        footer: Item { width: 1; height: 30 }
    }
}
