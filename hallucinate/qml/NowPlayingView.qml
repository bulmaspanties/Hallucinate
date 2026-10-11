import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import "."

// Now Playing, filling the window: the visualizer as a living backdrop in the cover's colours, the cover (or the
// record sliding out of its sleeve), the track and the controls. Controls fade away when the pointer rests.
// Opens by melting in: it fades up while the picture settles from slightly enlarged and blurred-looking.
Item {
    id: view
    objectName: "nowPlayingView"
    property bool open: false
    readonly property bool shown: open || melt.running
    readonly property bool vinyl: shell.nowPlayingVinyl
    property bool idle: false
    visible: opacity > 0
    opacity: open ? 1 : 0
    enabled: open
    focus: open
    Behavior on opacity { NumberAnimation { id: melt; duration: 520; easing.type: Easing.InOutCubic } }
    readonly property var styles: [
        { id: "liquid", t: "Liquid" }, { id: "aurora", t: "Aurora" }, { id: "nebula", t: "Nebula" }, { id: "bars", t: "Bars" }
    ]

    function toggle() { open = !open }
    onOpenChanged: { idle = false; if (open) idleTimer.restart() }
    Keys.onEscapePressed: open = false

    Rectangle { anchors.fill: parent; color: "#06040b" }

    Item {
        id: stage
        anchors.fill: parent
        // the melt: the scene settles from a slight zoom as it fades in
        scale: view.open ? 1 : 1.06
        Behavior on scale { NumberAnimation { duration: 700; easing.type: Easing.OutCubic } }

        Visualizer {
            id: vis
            objectName: "nowPlayingVisualizer"
            anchors.fill: parent
            style: shell.visualizerStyle
            active: view.shown
            quality: 0.45
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.5) }
                GradientStop { position: 0.6; color: Qt.rgba(0, 0, 0, 0.15) }
                GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.35) }
            }
        }

        RowLayout {
            id: content
            anchors { fill: parent; leftMargin: Math.max(48, parent.width * 0.08); rightMargin: Math.max(48, parent.width * 0.08)
                      topMargin: 90; bottomMargin: 70 }
            spacing: Math.max(36, parent.width * 0.05)

            // Cover, or the record half out of its sleeve
            Item {
                id: art
                readonly property real side: Math.min(content.height * 0.86, content.width * (view.vinyl ? 0.34 : 0.42))
                Layout.preferredWidth: side * (view.vinyl ? 1.5 : 1)
                Layout.preferredHeight: side
                Layout.alignment: Qt.AlignVCenter
                Behavior on Layout.preferredWidth { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }

                Item {
                    id: record
                    objectName: "vinylRecord"
                    width: art.side * 0.96; height: width
                    anchors.verticalCenter: parent.verticalCenter
                    x: view.vinyl ? art.side * 0.5 : art.side * 0.02
                    opacity: view.vinyl ? 1 : 0
                    Behavior on x { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
                    Behavior on opacity { NumberAnimation { duration: 300 } }
                    RotationAnimator on rotation {
                        from: 0; to: 360; duration: 1800 * 2  // 33⅓ rpm is too dizzy on screen; a calm half speed
                        loops: Animation.Infinite
                        running: view.vinyl && view.shown && player.playing
                    }
                    Rectangle {
                        anchors.fill: parent
                        radius: width / 2
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#1b1820" }
                            GradientStop { position: 0.5; color: "#0b0a0e" }
                            GradientStop { position: 1; color: "#18151d" }
                        }
                    }
                    // grooves
                    Repeater {
                        model: 9
                        Rectangle {
                            required property int index
                            anchors.centerIn: parent
                            width: record.width * (0.92 - index * 0.06); height: width
                            radius: width / 2
                            color: "transparent"
                            border.width: 1
                            border.color: Qt.rgba(1, 1, 1, index % 3 === 0 ? 0.08 : 0.04)
                        }
                    }
                    // a sheen that stays put while the record turns underneath it
                    Cover {
                        anchors.centerIn: parent
                        width: record.width * 0.36; height: width
                        radius: width / 2
                        source: player.hasTrack ? player.current.artUrl || "" : ""
                    }
                    Rectangle {
                        anchors.centerIn: parent
                        width: record.width * 0.03; height: width; radius: width / 2
                        color: "#06040b"
                    }
                }
                Rectangle {
                    anchors.centerIn: record
                    width: record.width; height: width; radius: width / 2
                    visible: record.opacity > 0
                    opacity: 0.5 * record.opacity
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.2; color: "transparent" }
                        GradientStop { position: 0.45; color: Qt.rgba(1, 1, 1, 0.09) }
                        GradientStop { position: 0.6; color: "transparent" }
                    }
                }

                // The sleeve
                Item {
                    id: sleeve
                    width: art.side; height: art.side
                    anchors.verticalCenter: parent.verticalCenter
                    Repeater {  // a soft shadow from stacked outlines (works without effects)
                        model: 6
                        Rectangle {
                            required property int index
                            anchors { fill: parent; margins: -(index + 1) * 3; topMargin: -(index + 1) * 3 + 10 }
                            radius: 22 + (index + 1) * 3
                            color: "transparent"
                            border.width: 3
                            border.color: Qt.rgba(0, 0, 0, 0.12 - index * 0.018)
                        }
                    }
                    Cover {
                        objectName: "nowPlayingCover"
                        anchors.fill: parent
                        radius: view.vinyl ? 6 : 22
                        source: player.hasTrack ? player.current.artUrl || "" : ""
                        fallback: player.hasTrack ? (player.current.title || "?").charAt(0) : ""
                    }
                }
            }

            // Track and controls
            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: 10
                Text {
                    Layout.fillWidth: true
                    text: player.hasTrack ? player.current.title : "Nothing playing"
                    color: "white"
                    font.family: Theme.displayFamily
                    font.pixelSize: Theme.fontSize(Math.max(26, Math.min(46, view.width / 30)))
                    font.weight: Font.Bold
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    visible: player.hasTrack
                    text: player.hasTrack ? player.current.artist : ""
                    color: Qt.rgba(1, 1, 1, 0.88)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(20)
                    elide: Text.ElideRight
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { view.open = false; Nav.openArtist(player.current.album_artist || player.current.artist) }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: player.hasTrack && (player.current.album || "").length > 0
                    text: player.hasTrack ? player.current.album + (player.current.year > 0 ? "  ·  " + player.current.year : "") : ""
                    color: Qt.rgba(1, 1, 1, 0.6)
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(15)
                    elide: Text.ElideRight
                    MouseArea {
                        anchors.fill: parent
                        enabled: player.hasTrack && (player.current.album_key || "").length > 0
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { view.open = false; Nav.openAlbum(player.current.album_key) }
                    }
                }
                Item { Layout.preferredHeight: 18 }
                WaveformSeek {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 640
                    Layout.preferredHeight: 44
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 640
                    Text { text: Theme.fmtTime(player.position); color: Qt.rgba(1, 1, 1, 0.65); font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                    Item { Layout.fillWidth: true }
                    Text { text: Theme.fmtTime(player.duration); color: Qt.rgba(1, 1, 1, 0.65); font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12) }
                }
                Row {
                    spacing: 14
                    IconButton { anchors.verticalCenter: parent.verticalCenter; icon: "shuffle"; size: 22; active: player.shuffle; onClicked: player.toggleShuffle() }
                    IconButton { anchors.verticalCenter: parent.verticalCenter; icon: "prev"; size: 24; onClicked: player.previous() }
                    Rectangle {
                        width: 64; height: 64; radius: 32
                        scale: bigPlay.pressed ? 0.94 : (bigPlay.containsMouse ? 1.06 : 1)
                        Behavior on scale { NumberAnimation { duration: 120 } }
                        color: "white"
                        Icon {
                            anchors.centerIn: parent
                            anchors.horizontalCenterOffset: player.playing ? 0 : 2
                            width: 24; height: 24
                            name: player.playing ? "pause" : "play"
                            color: "#120d18"
                        }
                        MouseArea { id: bigPlay; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: player.toggle() }
                        Accessible.role: Accessible.Button
                        Accessible.name: player.playing ? "Pause" : "Play"
                    }
                    IconButton { anchors.verticalCenter: parent.verticalCenter; icon: "next"; size: 24; onClicked: player.next() }
                    IconButton {
                        anchors.verticalCenter: parent.verticalCenter
                        icon: player.repeat === 2 ? "repeat1" : "repeat"
                        size: 22
                        active: player.repeat !== 0
                        onClicked: player.cycleRepeat()
                    }
                    IconButton {
                        anchors.verticalCenter: parent.verticalCenter
                        icon: "heart"; size: 22
                        active: player.hasTrack && userLib.likesRevision >= 0 && userLib.isLiked(player.current.path)
                        tip: "Like"
                        onClicked: if (player.hasTrack) userLib.toggleLike(player.current.path)
                    }
                }
            }
        }
    }

    // Top bar: leave, styles, vinyl, full screen. Fades out with the pointer at rest.
    Item {
        id: chrome
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 76
        opacity: view.idle ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 400 } }
        IconButton {
            objectName: "closeNowPlaying"
            anchors { left: parent.left; leftMargin: 22; verticalCenter: parent.verticalCenter }
            icon: "down"; size: 22
            tip: "Close (Esc)"
            onClicked: view.open = false
        }
        Row {
            anchors { right: parent.right; rightMargin: 22; verticalCenter: parent.verticalCenter }
            spacing: 8
            Repeater {
                model: view.styles
                Chip {
                    required property var modelData
                    text: modelData.t
                    selected: shell.visualizerStyle === modelData.id
                    onClicked: shell.setVisualizerStyle(modelData.id)
                }
            }
            Item { width: 6; height: 1 }
            IconButton {
                objectName: "vinylToggle"
                anchors.verticalCenter: parent.verticalCenter
                icon: "vinyl"; active: view.vinyl
                tip: view.vinyl ? "Show the cover" : "Show the record"
                onClicked: shell.setNowPlayingVinyl(!view.vinyl)
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                icon: "fullscreen"; active: Window.window && Window.window.visibility === Window.FullScreen
                tip: "Full screen (F11)"
                onClicked: view.toggleFullScreen()
            }
        }
    }
    Text {
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 }
        visible: !player.visualizerEnabled && player.visualizerAvailable && shell.visualizerStyle !== "bars"
        opacity: view.idle ? 0 : 0.6
        Behavior on opacity { NumberAnimation { duration: 400 } }
        text: "Turn on “React to the music” on the Visualizer page to make the backdrop move with the sound"
        color: "white"
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize(12)
    }

    function toggleFullScreen() {
        var w = Window.window
        if (!w) return
        w.visibility = w.visibility === Window.FullScreen ? Window.Windowed : Window.FullScreen
    }

    // Hide the controls and pointer after a few still seconds
    Timer { id: idleTimer; interval: 3000; onTriggered: view.idle = view.open }
    HoverHandler {
        cursorShape: view.idle ? Qt.BlankCursor : Qt.ArrowCursor
        onPointChanged: { view.idle = false; idleTimer.restart() }
    }
    // swallow clicks and wheel so nothing underneath reacts
    MouseArea { anchors.fill: parent; z: -2; onWheel: wheel => wheel.accepted = true }
}
