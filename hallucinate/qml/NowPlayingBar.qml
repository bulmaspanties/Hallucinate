import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Rectangle {
    id: bar
    property bool queueOpen: false
    property bool lyricsOpen: false
    signal toggleQueue()
    signal toggleLyrics()
    color: Theme.panel
    height: Theme.playerHeight

    Rectangle { width: parent.width; height: 1; color: Theme.border }

    // Now playing
    Row {
        anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
        width: Math.max(160, bar.width * 0.27)
        spacing: 12
        Cover {
            id: art
            width: 60; height: 60; radius: Theme.radiusSmall
            source: player.hasTrack ? player.current.artUrl : ""
            MouseArea {
                anchors.fill: parent
                enabled: player.hasTrack && player.current.album_key
                cursorShape: Qt.PointingHandCursor
                onClicked: Nav.openAlbum(player.current.album_key)
            }
        }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - art.width - 12
            spacing: 3
            Text {
                width: parent.width
                text: player.hasTrack ? player.current.title : "Nothing playing"
                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: player.error.length > 0 ? player.error : (player.hasTrack ? player.current.artist : "")
                color: player.error.length > 0 ? Theme.error : Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
                elide: Text.ElideRight
                MouseArea {
                    anchors.fill: parent
                    enabled: !player.error && player.hasTrack
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Nav.openArtist(player.current.album_artist)
                }
            }
            AudioInfoBadge {
                visible: player.showTrackInfo && player.hasTrack
                formatName: player.hasTrack ? player.current.codec || "" : ""
                bitrate: player.hasTrack ? player.current.bitrate || 0 : 0
            }
        }
    }

    // Transport
    Column {
        anchors.centerIn: parent
        width: Math.min(560, bar.width * 0.42)
        spacing: 4
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 6
            IconButton { icon: "shuffle"; active: player.shuffle; onClicked: player.toggleShuffle() }
            IconButton { icon: "prev"; onClicked: player.previous() }
            Rectangle {
                width: 42; height: 42; radius: 21
                color: pp.containsMouse ? Theme.accentHi : Theme.accent
                Icon {
                    anchors.centerIn: parent
                    width: 18; height: 18
                    name: player.playing ? "pause" : "play"
                    color: Theme.onAccent
                }
                MouseArea { id: pp; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: player.toggle() }
            }
            IconButton { icon: "next"; onClicked: player.next() }
            IconButton {
                icon: player.repeat === 2 ? "repeat1" : "repeat"
                active: player.repeat !== 0
                onClicked: player.cycleRepeat()
            }
        }
        RowLayout {
            width: parent.width
            spacing: 10
            Text { text: Theme.fmtTime(player.position); color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); Layout.preferredWidth: 38; horizontalAlignment: Text.AlignRight }
            StyledSlider {
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, player.duration)
                value: player.position
                enabled: player.hasTrack
                onMoved: player.seek(value)
            }
            Text { text: Theme.fmtTime(player.duration); color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(11); Layout.preferredWidth: 38 }
        }
    }

    // Volume + queue
    Row {
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        spacing: 6
        IconButton {
            icon: "more"; tip: "Speed and sleep timer"
            active: player.speed !== 1 || player.sleepRemaining >= 0 || player.sleepAfterTrack
            onClicked: playbackMenu.popup()
            PlaybackMenu { id: playbackMenu }
        }
        IconButton { icon: "expand"; tip: "Mini player (Ctrl+M)"; visible: true; onClicked: shell.toggleMini() }
        IconButton { icon: "note"; active: bar.lyricsOpen; tip: "Lyrics"; onClicked: bar.toggleLyrics() }
        IconButton { icon: "queue"; active: bar.queueOpen; onClicked: bar.toggleQueue() }
        Icon { anchors.verticalCenter: parent.verticalCenter; width: 18; height: 18; name: "volume"; color: Theme.textDim }
        StyledSlider {
            anchors.verticalCenter: parent.verticalCenter
            width: 100
            from: 0; to: 1
            value: player.volume
            onMoved: player.setVolume(value)
        }
    }
}
