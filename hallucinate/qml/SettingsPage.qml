import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import "."

Item {
    id: page
    objectName: "settings"
    property string query: ""
    readonly property var sectionIds: ["appearance", "features", "podcasts", "playback", "sound", "library", "servers", "sharing", "desktop", "about"]
    readonly property var sectionTitles: ["Appearance", "Features", "Podcasts", "Playback", "Sound", "Library", "Music servers", "Internet & sharing", "Desktop", "About"]

    function sectionItem(i) { return [sec_appearance, sec_features, sec_podcasts, sec_playback, sec_sound, sec_library, sec_servers, sec_sharing, sec_desktop, sec_about][i] }
    function jumpToSidebar() {
        jumpTo(1)
        var y = sidebarOrderBox.mapToItem(flick.contentItem, 0, 0).y - 20
        flick.contentY = Math.max(0, Math.min(y, flick.contentHeight - flick.height))
    }
    function jumpTo(i) {
        page.query = ""
        search.text = ""
        flick.contentY = Math.max(0, Math.min(sectionItem(i).y, flick.contentHeight - flick.height))
    }

    // Search and jump to a section; the page below scrolls
    Column {
        id: header
        x: 28; y: 20
        width: page.width - 56
        spacing: 12
        Row {
            width: parent.width
            spacing: 16
            Text { id: pageTitle; text: "Settings"; color: Theme.text; font.family: Theme.displayFamily; font.pixelSize: Theme.fontSize(25); font.weight: Font.Bold; textFormat: Text.PlainText }
            TextField {
                id: search
                objectName: "settingsSearch"
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(340, parent.width - pageTitle.width - 16)
                height: 36
                placeholderText: "Search settings"
                color: Theme.text
                placeholderTextColor: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(14)
                leftPadding: 14
                selectByMouse: true
                background: Rectangle { radius: height / 2; color: Theme.surface; border.color: search.activeFocus ? Theme.accent : Theme.border }
                onTextChanged: { page.query = text; flick.contentY = 0 }
                Keys.onEscapePressed: text = ""
            }
        }
        Flow {
            width: parent.width
            spacing: 8
            visible: page.query.length === 0
            Repeater {
                model: page.sectionTitles
                Chip {
                    required property string modelData
                    required property int index
                    visible: (modelData !== "Podcasts" || shell.features.podcasts !== false)
                             && (modelData !== "Music servers" || shell.features.servers === true)
                    text: modelData
                    onClicked: page.jumpTo(index)
                }
            }
        }
        Text {
            textFormat: Text.PlainText
            visible: page.query.length > 0
            text: noMatches ? "No settings match “" + page.query + "”" : "Showing settings that match “" + page.query + "”"
            readonly property bool noMatches: !(sec_appearance.matches || sec_features.matches || sec_podcasts.matches || sec_playback.matches || sec_sound.matches || sec_library.matches || sec_servers.matches || sec_sharing.matches || sec_desktop.matches || sec_about.matches)
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
        }
    }

    Flickable {
        id: flick
        anchors { left: parent.left; right: parent.right; top: header.bottom; topMargin: 14; bottom: parent.bottom }
        contentWidth: width
        contentHeight: settingsColumn.implicitHeight + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

    Column {
        id: settingsColumn
        x: 28
        width: page.width - 56
        spacing: 18

        SettingsSection {
            id: sec_appearance
            objectName: "settings_appearance"
            title: "Appearance"
            keywords: "theme colours font accent album art ambient motion reduce animation visualizer vinyl dark light system pride ribbon custom"
            query: page.query
            StyledCheck {
                text: "Show audio format and average bitrate on tracks"
                checked: player.showTrackInfo
                onToggled: player.setShowTrackInfo(checked)
                Accessible.name: "Show track audio format and average bitrate"
            }
            Text {
                textFormat: Text.PlainText
                text: "Shows compact format and approximate average bitrate badges in song rows and the now-playing bar."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
                wrapMode: Text.WordWrap
            }
            Row {
                spacing: 12
                Text {
                    textFormat: Text.PlainText
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Theme"
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                }
                StyledCombo {
                    id: themePicker
                    objectName: "themePicker"
                    width: 260
                    model: themeManager.availableThemes
                    currentIndex: Math.max(0, themeManager.availableThemes.indexOf(themeManager.currentTheme))
                    onActivated: themeManager.selectTheme(currentText)
                    contentItem: Text {
                        textFormat: Text.PlainText
                        objectName: "themePickerText"
                        leftPadding: 12
                        rightPadding: 2
                        text: themePicker.displayText
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(14)
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle {
                        implicitHeight: 38
                        radius: Theme.radius
                        color: Theme.surface
                        border.color: themePicker.activeFocus ? Theme.accent : Theme.border
                    }
                }
            }
            // Your own touches on the theme: an accent colour, light and dark following the system, a theme of your own
            Column {
                width: parent.width
                spacing: 8
                Text { textFormat: Text.PlainText; text: "Accent colour"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14) }
                Flow {
                    objectName: "accentSwatches"
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: ["", "#8f7bff", "#c08bff", "#ff7ab6", "#ff6b6b", "#ff9f43", "#ffd166", "#5fd38d",
                                "#2ec4b6", "#4cc9f0", "#5b8cff", "#e8e8f0"]
                        Rectangle {
                            required property string modelData
                            readonly property bool chosen: themeManager.accentOverride === modelData
                            width: 30; height: 30; radius: 15
                            color: modelData.length ? modelData : "transparent"
                            border.width: chosen ? 3 : 1
                            border.color: chosen ? Theme.text : Theme.border
                            Text {
                                visible: !modelData.length
                                anchors.centerIn: parent
                                text: "A"; textFormat: Text.PlainText
                                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); font.weight: Font.Bold
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: themeManager.setAccentOverride(modelData)
                                Accessible.role: Accessible.RadioButton
                                Accessible.name: modelData.length ? "Accent " + modelData : "The theme's own accent"
                                Accessible.checked: chosen
                                Accessible.onPressAction: themeManager.setAccentOverride(modelData)
                            }
                        }
                    }
                    TextField {
                        id: accentHex
                        objectName: "accentHex"
                        width: 120; height: 30
                        placeholderText: "#hex"
                        text: themeManager.accentOverride
                        selectByMouse: true
                        Accessible.name: "Accent colour as a hex code"
                        onAccepted: themeManager.setAccentOverride(text)
                    }
                }
                StyledCheck {
                    objectName: "followSystemTheme"
                    text: "Follow the system's light or dark mode"
                    checked: themeManager.followSystem
                    onToggled: themeManager.setFollowSystem(checked)
                }
                Flow {
                    visible: themeManager.followSystem
                    width: parent.width
                    spacing: 10
                    Text { textFormat: Text.PlainText; text: "Light"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); height: 38; verticalAlignment: Text.AlignVCenter }
                    StyledCombo {
                        width: 200
                        model: themeManager.availableThemes
                        currentIndex: Math.max(0, themeManager.availableThemes.indexOf(themeManager.lightTheme))
                        onActivated: themeManager.setSystemThemes(currentText, themeManager.darkTheme)
                        Accessible.name: "Theme in light mode"
                    }
                    Text { textFormat: Text.PlainText; text: "Dark"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); height: 38; verticalAlignment: Text.AlignVCenter }
                    StyledCombo {
                        width: 200
                        model: themeManager.availableThemes
                        currentIndex: Math.max(0, themeManager.availableThemes.indexOf(themeManager.darkTheme))
                        onActivated: themeManager.setSystemThemes(themeManager.lightTheme, currentText)
                        Accessible.name: "Theme in dark mode"
                    }
                }
                PillButton { objectName: "makeTheme"; text: "Make my own theme…"; onClicked: themeEditor.open() }
            }
            ThemeEditor { id: themeEditor }
            StyledCheck {
                objectName: "ambientMotion"
                text: "Animated background (slowly drifting colours from the current cover)"
                checked: shell.ambientMotion
                onToggled: shell.setAmbientMotion(checked)
            }
            StyledCheck {
                objectName: "reduceMotion"
                text: "Reduce motion (no page transitions, zooms, spinning record or growing buttons)"
                checked: shell.reduceMotion
                onToggled: shell.setReduceMotion(checked)
            }
            CheckBox {
                id: albumAccentToggle
                text: "Use album-art accent color"
                checked: themeManager.albumArtAccent
                onToggled: themeManager.setAlbumArtAccent(checked)
                contentItem: Text {
                    textFormat: Text.PlainText
                    text: albumAccentToggle.text
                    leftPadding: 30
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                    verticalAlignment: Text.AlignVCenter
                }
                indicator: Rectangle {
                    implicitWidth: 20
                    implicitHeight: 20
                    radius: Theme.radius / 2
                    x: albumAccentToggle.leftPadding
                    y: parent.height / 2 - height / 2
                    color: albumAccentToggle.checked ? Theme.accent : Theme.surface
                    border.color: albumAccentToggle.checked ? Theme.accent : Theme.border
                    Text {
                        textFormat: Text.PlainText
                        anchors.centerIn: parent
                        text: albumAccentToggle.checked ? "✓" : ""
                        color: Theme.onAccent
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSize(13)
                    }
                }
            }
            Text {
                textFormat: Text.PlainText
                text: "Custom themes: " + themeManager.userThemeDirectory + "/*.json"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(12)
            }
            PillButton {
                text: "Reload themes"
                onClicked: themeManager.reloadThemes()
            }

        }
        SettingsSection {
            id: sec_features
            objectName: "settings_features"
            title: "Features"
            keywords: "hide show turn off sidebar pages order rearrange move arrange home cards internet radio stations podcasts lyrics stats recap history visualizer health folders liked"
            query: page.query
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: "Turn off what you don't use. It disappears everywhere (the sidebar, Ctrl+K, menus and shortcuts) and nothing is lost: switch it back on and it's all still there."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
                wrapMode: Text.WordWrap
            }
            component FeatureGroup: Column {
                property string heading
                property var items: []
                width: parent ? parent.width : 400
                spacing: 6
                Text {
                    textFormat: Text.PlainText
                    text: parent.heading
                    color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); font.weight: Font.DemiBold
                }
                Flow {
                    width: parent.width
                    spacing: 4
                    Repeater {
                        model: parent.parent.items
                        StyledCheck {
                            required property var modelData
                            objectName: "feature_" + modelData[0]
                            width: Math.max(220, implicitWidth + 12)
                            text: modelData[1]
                            checked: shell.features[modelData[0]] !== false
                            onToggled: shell.setFeature(modelData[0], checked)
                        }
                    }
                }
            }
            FeatureGroup {
                heading: "Listening"
                items: [["stations", "Internet radio"], ["podcasts", "Podcasts"], ["servers", "Music servers"],
                        ["lyrics", "Lyrics"], ["visualizer", "Visualizer"]]
            }
            FeatureGroup {
                heading: "Pages"
                items: [["liked", "Liked Songs"], ["folders", "Folders"], ["stats", "Stats"], ["history", "History"],
                        ["recap", "Recap"], ["health", "Library health"]]
            }
            FeatureGroup {
                heading: "Home"
                items: [["homeRandom", "Random album"], ["homeListening", "Listening card"],
                        ["homeFacts", "Library facts"], ["homeShelves", "Album shelves"]]
            }
            Column {
                id: sidebarOrderBox
                objectName: "sidebarOrder"
                width: parent.width
                spacing: 6
                readonly property var names: ({ home: "Home", albums: "Albums", artists: "Artists", songs: "Songs",
                    folders: "Folders", liked: "Liked Songs", stats: "Stats", history: "History", recap: "Recap",
                    visualizer: "Visualizer", stations: "Internet radio", podcasts: "Podcasts" })
                readonly property var shown: shell.sidebarOrder.filter(function (p) { return shell.features[p] !== false })
                Row {
                    width: parent.width
                    spacing: 12
                    Text {
                        textFormat: Text.PlainText
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Sidebar order"
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); font.weight: Font.DemiBold
                    }
                    PillButton { objectName: "resetSidebarOrder"; height: 30; text: "Reset"; onClicked: shell.resetSidebarOrder() }
                }
                Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "Move pages up or down here, drag them in the sidebar, or right-click one there. With a page focused, Alt+Up and Alt+Down move it too."
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
                }
                Repeater {
                    model: sidebarOrderBox.shown
                    Rectangle {
                        required property string modelData
                        required property int index
                        objectName: "sidebarOrder_" + modelData
                        width: Math.min(380, sidebarOrderBox.width)
                        height: 34
                        radius: Theme.radiusSmall
                        color: Theme.surface
                        Text {
                            textFormat: Text.PlainText
                            anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
                            text: (index + 1) + ".  " + sidebarOrderBox.names[modelData]
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                        }
                        Row {
                            anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                            spacing: 2
                            IconButton {
                                icon: "up"; size: 16
                                enabled: index > 0
                                opacity: enabled ? 1 : 0.35
                                tip: "Move " + sidebarOrderBox.names[modelData] + " up"
                                onClicked: shell.moveSidebarPage(modelData, -1)
                            }
                            IconButton {
                                icon: "down"; size: 16
                                enabled: index < sidebarOrderBox.shown.length - 1
                                opacity: enabled ? 1 : 0.35
                                tip: "Move " + sidebarOrderBox.names[modelData] + " down"
                                onClicked: shell.moveSidebarPage(modelData, 1)
                            }
                        }
                    }
                }
            }
        }

        SettingsSection {
            id: sec_podcasts
            objectName: "settings_podcasts"
            title: "Podcasts"
            keywords: "podcast episodes skip back forward seconds feeds check refresh download keep remove storage played speed next"
            query: page.query
            visible: matches && shell.features.podcasts !== false
            readonly property var o: podcasts.options
            function secs(list) { return list.map(function (n) { return n + " seconds" }) }
            OptionCombo {
                label: "Skip back"
                values: [5, 10, 15, 30, 45, 60]; labels: sec_podcasts.secs(values)
                current: sec_podcasts.o.skipBack
                onPicked: function (v) { podcasts.setOption("skipBack", v) }
            }
            OptionCombo {
                label: "Skip forward"
                values: [10, 15, 30, 45, 60, 90]; labels: sec_podcasts.secs(values)
                current: sec_podcasts.o.skipForward
                onPicked: function (v) { podcasts.setOption("skipForward", v) }
            }
            OptionCombo {
                label: "Check for new episodes"
                values: [1, 2, 4, 8, 12, 24, 0]
                labels: ["Every hour", "Every 2 hours", "Every 4 hours", "Every 8 hours", "Twice a day", "Once a day", "Only when I ask"]
                current: sec_podcasts.o.refreshHours
                onPicked: function (v) { podcasts.setOption("refreshHours", v) }
            }
            OptionCombo {
                label: "After an episode"
                values: ["next", "stop"]
                labels: ["Play the show's next one", "Stop"]
                current: sec_podcasts.o.afterEpisode
                onPicked: function (v) { podcasts.setOption("afterEpisode", v) }
            }
            OptionCombo {
                label: "Played when this close to the end"
                values: [10, 30, 45, 60, 120, 300]
                labels: ["10 seconds", "30 seconds", "45 seconds", "1 minute", "2 minutes", "5 minutes"]
                current: sec_podcasts.o.playedWindow
                onPicked: function (v) { podcasts.setOption("playedWindow", v) }
            }
            StyledCheck {
                objectName: "notifyNewEpisodes"
                text: "Tell me when a show I follow has a new episode (a desktop notification)"
                checked: sec_podcasts.o.notifyNew === 1
                onToggled: podcasts.setOption("notifyNew", checked ? 1 : 0)
            }
            Text { textFormat: Text.PlainText; text: "Downloads"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold }
            OptionCombo {
                label: "A show you follow downloads"
                values: [0, 1, 2, 3, 5]
                labels: ["Nothing by itself", "Its newest episode", "Its newest 2", "Its newest 3", "Its newest 5"]
                current: sec_podcasts.o.newShowDownloads
                onPicked: function (v) { podcasts.setOption("newShowDownloads", v) }
            }
            OptionCombo {
                label: "Keep downloads"
                values: ["played", "latest", "forever"]
                labels: ["Until they're played", "Only the newest of each show", "Until I remove them"]
                current: sec_podcasts.o.keep
                onPicked: function (v) { podcasts.setOption("keep", v) }
            }
            OptionCombo {
                visible: sec_podcasts.o.keep === "latest"
                label: "Newest to keep per show"
                values: [1, 2, 3, 5, 10]; labels: ["1", "2", "3", "5", "10"]
                current: sec_podcasts.o.keepCount
                onPicked: function (v) { podcasts.setOption("keepCount", v) }
            }
            Row {
                spacing: 12
                Text {
                    textFormat: Text.PlainText
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Downloads take " + Theme.fmtBytes(podcasts.downloadsSize)
                    color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14)
                }
                PillButton { text: "Remove all downloads"; enabled: podcasts.downloadsSize > 0; onClicked: removeDownloadsDlg.open() }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Each show can have its own speed, skip its intro or outro, list oldest first and download its newest episodes: open the show and choose Show settings. Episodes in a folder you added are your own files and are never removed."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
            }
            ConfirmDialog {
                id: removeDownloadsDlg
                title: "Remove every downloaded episode?"
                body: "The files go; the episodes stay, and play from the web until downloaded again."
                confirmText: "Remove downloads"
                destructive: true
                onAccepted: podcasts.removeAllDownloads()
            }
        }

        SettingsSection {
            id: sec_playback
            objectName: "settings_playback"
            title: "Playback"
            keywords: "output device audio replaygain loudness crossfade gapless speed sleep"
            query: page.query
            Row {
                spacing: 12
                Text { anchors.verticalCenter: parent.verticalCenter; text: "Output device"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); textFormat: Text.PlainText }
                StyledCombo {
                    id: deviceCombo
                    objectName: "outputDevice"
                    width: 360
                    model: player.outputDevices
                    textRole: "name"
                    currentIndex: player.outputDevices.findIndex(d => d.key === player.outputDevice)
                    onActivated: player.setOutputDevice(player.outputDevices[currentIndex].key)
                    // Activating breaks the binding above; re-sync when devices come and go.
                    Connections {
                        target: player
                        function onOutputDevicesChanged() {
                            deviceCombo.currentIndex = player.outputDevices.findIndex(d => d.key === player.outputDevice)
                        }
                    }
                }
            }
            Row {
                spacing: 12
                Text { anchors.verticalCenter: parent.verticalCenter; text: "ReplayGain"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); textFormat: Text.PlainText }
                StyledCombo {
                    objectName: "rgMode"
                    model: ["Off", "Track", "Album"]
                    currentIndex: ["off", "track", "album"].indexOf(player.replayGainMode)
                    onActivated: player.setReplayGainMode(["off", "track", "album"][currentIndex])
                }
                Text { anchors.verticalCenter: parent.verticalCenter; text: "Preamp " + player.replayGainPreamp.toFixed(1) + " dB"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); textFormat: Text.PlainText }
                StyledSlider {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 140
                    from: -15; to: 15; stepSize: 0.5
                    value: player.replayGainPreamp
                    onMoved: player.setReplayGainPreamp(value)
                }
            }
            StyledCheck {
                objectName: "autoReplayGain"
                text: "Measure new music by itself after each scan"
                checked: replayGain.auto
                onToggled: replayGain.setAuto(checked)
            }
            Row {
                spacing: 12
                PillButton {
                    objectName: "analyseReplayGain"
                    text: replayGain.busy ? "Stop measuring" : "Measure songs without ReplayGain"
                    onClicked: replayGain.busy ? replayGain.cancel() : replayGain.analyseMissing()
                }
                Text {
                    textFormat: Text.PlainText
                    anchors.verticalCenter: parent.verticalCenter
                    text: replayGain.busy ? "Measured " + replayGain.done + " of " + replayGain.total + " songs…"
                        : "Measures loudness (EBU R128) for songs whose files have no ReplayGain tags. Files aren't changed."
                    color: Theme.textDim
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(12)
                }
            }
            Row {
                spacing: 12
                Text { anchors.verticalCenter: parent.verticalCenter; text: "Crossfade " + (player.crossfade > 0 ? player.crossfade + " s" : "off"); color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); textFormat: Text.PlainText }
                StyledSlider {
                    objectName: "crossfade"
                    anchors.verticalCenter: parent.verticalCenter
                    width: 200
                    from: 0; to: 12; stepSize: 1
                    value: player.crossfade
                    onMoved: player.setCrossfade(value)
                }
            }
            Text { text: "Gapless playback is always on; with crossfade off, consecutive tracks play back to back."; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12); textFormat: Text.PlainText }
        }
        SettingsSection {
            id: sec_sound
            objectName: "settings_sound"
            title: "Sound"
            keywords: "equalizer eq bass treble headphones autoeq crossfeed"
            query: page.query
            EqualizerPanel {}
            Row {
                spacing: 12
                Text { anchors.verticalCenter: parent.verticalCenter; text: "Headphone crossfeed"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); textFormat: Text.PlainText }
                StyledCombo {
                    objectName: "crossfeed"
                    enabled: player.eqAvailable
                    model: ["Off", "Light", "Medium", "Strong"]
                    currentIndex: Math.max(0, player.crossfeedPresets.indexOf(player.crossfeed))
                    onActivated: player.setCrossfeed(player.crossfeedPresets[currentIndex])
                }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Lets each ear hear a little of the other channel, as from speakers. Old stereo recordings with "
                    + "instruments hard left or right get much easier on the ears over headphones."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
            }

        }
        SettingsSection {
            id: sec_library
            objectName: "settings_library"
            title: "Library"
            keywords: "music folders scan rescan health tags files ratings stars cover art cover.jpg embed import strawberry clementine rhythmbox musicbee itunes foobar playlists hidden removed restore albums backup export your data move computer"
            query: page.query
            Text {
                textFormat: Text.PlainText
                text: "Folders are scanned in the background and watched for changes."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            StyledCheck {
                objectName: "ratingsInFiles"
                text: "Save star ratings in the songs' own tags too, so other players see them"
                checked: userLib.ratingsInFiles
                onToggled: userLib.setRatingsInFiles(checked)
            }
            StyledCheck {
                objectName: "coversToFolder"
                text: "Save covers you add as cover.jpg in the album's folder"
                checked: metaEditor.coversToFolder
                onToggled: metaEditor.setCoversToFolder(checked)
            }
            StyledCheck {
                objectName: "embedCovers"
                text: "Also embed covers you add in the songs themselves"
                checked: metaEditor.embedCovers
                onToggled: metaEditor.setEmbedCovers(checked)
            }
            Row {
                visible: library.hiddenCount > 0
                spacing: 12
                Text {
                    textFormat: Text.PlainText
                    objectName: "hiddenCount"
                    anchors.verticalCenter: parent.verticalCenter
                    text: library.hiddenCount + (library.hiddenCount === 1 ? " file" : " files")
                          + " removed from the library (still on disk)"
                    color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                }
                PillButton {
                    objectName: "restoreHidden"
                    height: 32
                    text: "Bring them back"
                    onClicked: { library.restoreHidden(); Nav.notify("Rescanning to bring them back…") }
                }
            }

            Row {
                objectName: "backupRow"
                spacing: 10
                Text {
                    textFormat: Text.PlainText
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Your likes, ratings, playlists, history, stations and shows"
                    color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                }
                PillButton { objectName: "exportBackup"; height: 32; text: "Back up…"; onClicked: backupSaveDlg.open() }
                PillButton { objectName: "importBackup"; height: 32; text: "Restore…"; onClicked: backupOpenDlg.open() }
            }
            FileDialog {
                id: backupSaveDlg
                title: "Back up your data"
                fileMode: FileDialog.SaveFile
                defaultSuffix: "hallucinate-backup"
                nameFilters: ["Hallucinate backup (*.hallucinate-backup)"]
                onAccepted: Nav.notify(shell.exportBackup(selectedFile.toString()))
            }
            FileDialog {
                id: backupOpenDlg
                title: "Restore from a backup"
                nameFilters: ["Hallucinate backup (*.hallucinate-backup)", "All files (*)"]
                onAccepted: Nav.notify(shell.importBackup(selectedFile.toString()))
            }
            Repeater {
                model: library.folders
                Rectangle {
                    required property var modelData
                    width: parent.width; height: 48; radius: Theme.radius
                    color: Theme.surface
                    Text {
                        textFormat: Text.PlainText
                        anchors { left: parent.left; leftMargin: 16; right: rm.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        text: modelData
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); elide: Text.ElideMiddle
                    }
                    IconButton {
                        id: rm
                        anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        icon: "close"; size: 14
                        tip: "Remove this folder from the library"
                        onClicked: Nav.removeFolder(modelData)
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
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(14)
                    leftPadding: 14
                    background: Rectangle { radius: Theme.radiusLarge; color: Theme.surface; border.color: pathField.activeFocus ? Theme.accent : Theme.border }
                    onAccepted: add.clicked()
                }
                PillButton {
                    id: add
                    primary: true
                    text: "Add folder"
                    onClicked: { library.addFolder(pathField.text); pathField.text = "" }
                }
                PillButton { text: "Rescan now"; onClicked: library.rescan() }
                PillButton { objectName: "openHealth"; visible: shell.features.health !== false; text: "Library health"; onClicked: Nav.openHealth() }
            }
            ScanBar { width: parent.width }
            Text {
                textFormat: Text.PlainText
                visible: !library.scanning && library.status.length > 0
                text: library.status
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                visible: library.missingFolders.length > 0
                wrapMode: Text.WordWrap
                text: "Folder not found or unreadable: " + library.missingFolders.join(", ")
                color: Theme.error; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Text {
                textFormat: Text.PlainText
                visible: library.unreadableFiles > 0 && !library.scanning
                text: library.unreadableFiles + " files could not be read and were skipped."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            PillButton { text: "Choose folder…"; onClicked: picker.open() }
            FolderPicker { id: picker }

            Rectangle { width: parent.width; height: 1; color: Theme.border }
            Rectangle { width: parent.width; height: 1; color: Theme.border }
            Text { text: "From another player"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold; textFormat: Text.PlainText }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Bring over play counts, skips, ratings and playlists from Strawberry, Clementine, Rhythmbox, MusicBee "
                    + "or iTunes. Songs are matched to your library; importing again never counts anything twice, and "
                    + "ratings you set here are kept."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Flow {
                width: parent.width
                spacing: 10
                Repeater {
                    id: foundPlayers
                    model: userLib.otherPlayerLibraries()
                    PillButton {
                        required property var modelData
                        text: "Import from " + modelData.name
                        enabled: !userLib.playerImportBusy
                        onClicked: userLib.importFromPlayer(modelData.path)
                    }
                }
                PillButton {
                    objectName: "importPlayerFile"
                    text: foundPlayers.count ? "Choose another library file…" : "Choose a library file…"
                    enabled: !userLib.playerImportBusy
                    onClicked: playerFile.open()
                }
                PillButton {
                    text: userLib.playerImportBusy ? "Importing…" : "foobar2000: play counts from tags"
                    enabled: !userLib.playerImportBusy
                    onClicked: userLib.importTagStatistics()
                }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "MusicBee: turn on Preferences → Library → “make library and playlists accessible to other "
                    + "applications”, then choose its iTunes Music Library.xml. foobar2000 keeps its statistics to "
                    + "itself, so write them to the files with foo_playcount first; its playlists come over as M3U files."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
            }
            FileDialog {
                id: playerFile
                title: "Choose another player's library"
                nameFilters: ["Player libraries (*.db *.xml)", "All files (*)"]
                onAccepted: userLib.importFromPlayer(selectedFile.toString())
            }
        }
        SettingsSection {
            id: sec_servers
            objectName: "settings_servers"
            title: "Music servers"
            keywords: "server servers subsonic navidrome gonic airsonic ampache jellyfin emby stream remote network nas sync"
            query: page.query
            visible: matches && shell.features.servers === true
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Songs on your Jellyfin server, or your Navidrome, Gonic, Airsonic or other Subsonic server, join your library and play like your own files. The sign-in stays in your system keyring (for Jellyfin, only the access token it gives). Songs from a server that can't be reached are skipped."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Repeater {
                model: servers.servers
                Row {
                    id: serverRow
                    required property var modelData
                    objectName: "server_" + modelData.id
                    spacing: 12
                    width: parent ? parent.width : 0
                    Column {
                        width: serverRow.width - syncButton.width - removeButton.width - 24
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            textFormat: Text.PlainText
                            width: parent.width
                            elide: Text.ElideRight
                            text: serverRow.modelData.name + "  ·  " + serverRow.modelData.user
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); font.weight: Font.DemiBold
                        }
                        Text {
                            textFormat: Text.PlainText
                            width: parent.width
                            elide: Text.ElideRight
                            readonly property var m: serverRow.modelData
                            text: (m.status === "syncing" ? "Reading its songs…"
                                   : m.status === "checking" ? "Checking…"
                                   : m.status === "down" ? "Can't be reached" + (m.error ? ": " + m.error : "") + " (tried again every few minutes)"
                                   : m.status === "error" ? m.error
                                   : m.songs.toLocaleString(Qt.locale(), "f", 0) + (m.songs === 1 ? " song" : " songs")
                                     + (m.error ? "  ·  " + m.error : ""))
                                  + (m.secure ? "" : "  ·  not a secure link")
                            color: m.status === "down" || m.status === "error" ? Theme.error : Theme.textDim
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
                        }
                    }
                    PillButton {
                        id: syncButton
                        anchors.verticalCenter: parent.verticalCenter
                        height: 32
                        text: "Sync now"
                        enabled: !serverRow.modelData.busy
                        onClicked: servers.sync(serverRow.modelData.id)
                    }
                    PillButton {
                        id: removeButton
                        anchors.verticalCenter: parent.verticalCenter
                        height: 32
                        text: "Remove"
                        onClicked: { removeServerDlg.serverId = serverRow.modelData.id; removeServerDlg.what = serverRow.modelData.name; removeServerDlg.open() }
                    }
                }
            }
            PillButton {
                objectName: "addServer"
                primary: true
                text: "Add a server…"
                onClicked: addServerDlg.open()
            }
            ConfirmDialog {
                id: removeServerDlg
                property string serverId: ""
                property string what: ""
                title: "Remove this server?"
                confirmText: "Remove server"
                destructive: true
                body: "Its songs leave your library and its password leaves the keyring. Nothing on the server changes."
                onAccepted: servers.removeServer(serverId)
            }
            Dialog {
                id: addServerDlg
                objectName: "addServerDialog"
                parent: Overlay.overlay
                anchors.centerIn: parent
                width: Math.min(460, (parent ? parent.width : 460) - 40)
                modal: true
                title: "Add a music server"
                standardButtons: Dialog.Ok | Dialog.Cancel
                property string kind: "subsonic"
                readonly property bool ready: serverLink.text.trim().length > 0 && serverUser.text.trim().length > 0
                                              && serverPassword.text.length > 0
                function okLater() { var b = standardButton(Dialog.Ok); if (b) b.enabled = ready }
                onReadyChanged: okLater()
                onOpened: { kind = "subsonic"; serverLink.text = ""; serverUser.text = ""; serverPassword.text = ""; serverName.text = ""; okLater(); serverLink.forceActiveFocus() }
                onAccepted: {
                    servers.addServer(serverLink.text.trim(), serverUser.text.trim(), serverPassword.text, serverName.text.trim(), kind)
                    serverPassword.text = ""  // don't keep it in the field
                }
                onRejected: serverPassword.text = ""
                Column {
                    width: addServerDlg.availableWidth
                    spacing: 10
                    Row {
                        spacing: 6
                        Chip {
                            objectName: "serverKindSubsonic"
                            text: "Subsonic (Navidrome, Gonic…)"
                            selected: addServerDlg.kind === "subsonic"
                            onClicked: addServerDlg.kind = "subsonic"
                        }
                        Chip {
                            objectName: "serverKindJellyfin"
                            text: "Jellyfin"
                            selected: addServerDlg.kind === "jellyfin"
                            onClicked: addServerDlg.kind = "jellyfin"
                        }
                    }
                    TextField {
                        id: serverLink; objectName: "serverLink"; width: parent.width; selectByMouse: true
                        placeholderText: "Server link (https://music.example.com)"; Accessible.name: "Server link"
                        onAccepted: if (addServerDlg.ready) addServerDlg.accept()
                    }
                    Text {
                        visible: serverLink.text.trim().length > 0 && !servers.linkIsSecure(serverLink.text)
                        textFormat: Text.PlainText
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "This isn't a secure (https) link and isn't on your home network: anyone on the networks in between could see what you play and reuse your sign-in."
                        color: Theme.error; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
                    }
                    TextField {
                        id: serverUser; objectName: "serverUser"; width: parent.width; selectByMouse: true
                        placeholderText: "User name"; Accessible.name: "User name"
                        onAccepted: if (addServerDlg.ready) addServerDlg.accept()
                    }
                    TextField {
                        id: serverPassword; objectName: "serverPassword"; width: parent.width
                        echoMode: TextInput.Password; placeholderText: "Password"; Accessible.name: "Password"
                        onAccepted: if (addServerDlg.ready) addServerDlg.accept()
                    }
                    TextField {
                        id: serverName; width: parent.width; selectByMouse: true
                        placeholderText: "Name (optional)"; Accessible.name: "Server name"
                        onAccepted: if (addServerDlg.ready) addServerDlg.accept()
                    }
                }
            }
        }
        SettingsSection {
            id: sec_sharing
            objectName: "settings_sharing"
            title: "Internet & sharing"
            keywords: "offline mode internet network privacy connection lyrics lrclib last.fm lastfm listenbrainz scrobble discord rich presence history import account radio stations podcasts episodes"
            query: page.query
            Text { text: "Offline mode"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold; textFormat: Text.PlainText }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Hallucinate makes no internet connections at all: no lyrics or cover lookups, internet radio, podcast updates, scrobbling, headphone EQ downloads or update checks. Scrobbles wait and are sent when you turn it off. Discord status talks only to the Discord app on this computer, so it keeps its own switch below (it shows no cover art while offline)."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            StyledCheck {
                objectName: "lyricsOnline"
                visible: shell.features.lyrics !== false
                text: "Find lyrics online for songs that have none (sends the song's artist, title and album to LRCLIB)"
                checked: lyricsCtl.onlineLookup
                onToggled: lyricsCtl.setOnlineLookup(checked)
            }
            StyledCheck {
                objectName: "scrobbleStations"
                visible: shell.features.stations !== false
                text: "Count songs heard on internet radio on Last.fm and ListenBrainz"
                checked: stations.scrobble
                onToggled: stations.setScrobble(checked)
            }
            StyledCheck {
                objectName: "scrobblePodcasts"
                visible: shell.features.podcasts !== false
                text: "Count podcast episodes on Last.fm and ListenBrainz (as the show and the episode's title)"
                checked: podcasts.scrobble
                onToggled: podcasts.setScrobble(checked)
            }
            StyledCheck {
                objectName: "syncLoves"
                visible: scrobbler.connected && shell.features.liked !== false
                text: "Liking a song loves it on Last.fm (and unliking unloves it)"
                checked: scrobbler.syncLoves
                onToggled: scrobbler.setSyncLoves(checked)
            }
            PillButton {
                objectName: "importLoves"
                visible: scrobbler.connected && shell.features.liked !== false
                text: scrobbler.lovesBusy ? "Fetching your loves…" : "Like the songs I've loved on Last.fm"
                enabled: !scrobbler.lovesBusy
                onClicked: scrobbler.importLoves()
            }
            StyledCheck {
                objectName: "offlineMode"
                text: "Offline mode"
                checked: shell.offlineMode
                onToggled: shell.setOfflineMode(checked)
            }
            Text { text: "Last.fm"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold; textFormat: Text.PlainText }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Connect your Last.fm account to send now-playing updates and scrobbles after listening to half a track or four minutes, whichever comes first. API credentials are stored in the system keyring."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Register an API application, then enter its key and secret. Last.fm account authorization opens in your browser."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Row {
                spacing: 10
                TextField {
                    id: apiKey
                    width: 250; height: 38
                    placeholderText: "Last.fm API key"
                    color: Theme.text; placeholderTextColor: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); leftPadding: 14
                    background: Rectangle { radius: Theme.radiusLarge; color: Theme.surface; border.color: apiKey.activeFocus ? Theme.accent : Theme.border }
                }
                TextField {
                    id: apiSecret
                    width: 250; height: 38
                    placeholderText: "Last.fm API secret"
                    echoMode: TextInput.Password
                    color: Theme.text; placeholderTextColor: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); leftPadding: 14
                    background: Rectangle { radius: Theme.radiusLarge; color: Theme.surface; border.color: apiSecret.activeFocus ? Theme.accent : Theme.border }
                }
                PillButton {
                    text: "Save API credentials"
                    primary: true
                    enabled: apiKey.text.length > 0 && apiSecret.text.length > 0 && !scrobbler.busy
                    onClicked: {
                        scrobbler.setApiCredentials(apiKey.text, apiSecret.text)
                        apiSecret.text = ""
                    }
                }
            }
            Row {
                spacing: 10
                PillButton {
                    text: "Get API credentials"
                    onClicked: Qt.openUrlExternally("https://www.last.fm/api/account/create")
                }
                PillButton {
                    visible: !scrobbler.connected
                    primary: true
                    text: scrobbler.busy ? "Connecting…" : "Connect Last.fm"
                    enabled: scrobbler.configured && !scrobbler.busy && !shell.offlineMode
                    onClicked: scrobbler.connectAccount()
                }
                PillButton {
                    visible: scrobbler.authorizationUrl.length > 0 && !scrobbler.connected
                    text: "Open authorization"
                    onClicked: scrobbler.openAuthorizationUrl()
                }
                PillButton {
                    visible: scrobbler.authorizationUrl.length > 0 && !scrobbler.connected
                    primary: true
                    text: "I've authorized"
                    enabled: !scrobbler.busy
                    onClicked: scrobbler.completeAuthorization()
                }
                PillButton {
                    visible: scrobbler.connected
                    text: "Disconnect Last.fm"
                    enabled: !scrobbler.busy
                    onClicked: scrobbler.disconnectAccount()
                }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: scrobbler.status + (scrobbler.pendingCount > 0 ? " · " + scrobbler.pendingCount + " queued scrobbles" : "")
                color: scrobbler.connected ? Theme.accent : Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(13)
                wrapMode: Text.WordWrap
            }
            Text { text: "ListenBrainz"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold; textFormat: Text.PlainText }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Connect with a ListenBrainz user token to send now-playing updates and listens. Tokens stay in the system keyring; failed submissions remain queued for retry."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Row {
                spacing: 10
                TextField {
                    id: lbToken
                    width: 320; height: 38
                    visible: !listenbrainz.connected
                    placeholderText: "ListenBrainz user token"
                    echoMode: TextInput.Password
                    color: Theme.text; placeholderTextColor: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); leftPadding: 14
                    background: Rectangle { radius: Theme.radiusLarge; color: Theme.surface; border.color: lbToken.activeFocus ? Theme.accent : Theme.border }
                }
                PillButton {
                    visible: !listenbrainz.connected
                    primary: true
                    text: listenbrainz.busy ? "Validating…" : "Connect ListenBrainz"
                    enabled: lbToken.text.length > 0 && !listenbrainz.busy
                    onClicked: { listenbrainz.connectToken(lbToken.text, ""); lbToken.text = "" }
                }
                PillButton {
                    visible: listenbrainz.connected
                    text: "Disconnect ListenBrainz"
                    enabled: !listenbrainz.busy
                    onClicked: listenbrainz.disconnectAccount()
                }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: listenbrainz.status + (listenbrainz.pendingCount > 0 ? " · " + listenbrainz.pendingCount + " queued listens" : "")
                color: listenbrainz.connected ? Theme.accent : Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); wrapMode: Text.WordWrap
            }
            Text { text: "Import listening history"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold; textFormat: Text.PlainText }
            Row {
                spacing: 10
                StyledCombo {
                    id: historySource
                    width: 150
                    model: ["ListenBrainz", "Last.fm"]
                }
                TextField {
                    id: historyUser
                    width: 260; height: 38
                    placeholderText: historySource.currentIndex === 0 && listenbrainz.connected ? "Username (blank = connected account)" : "Username"
                    color: Theme.text; placeholderTextColor: Theme.textDim
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); leftPadding: 14
                    background: Rectangle { radius: Theme.radiusLarge; color: Theme.surface; border.color: historyUser.activeFocus ? Theme.accent : Theme.border }
                }
                PillButton {
                    primary: true
                    text: listenbrainz.importing ? "Importing…" : "Import history"
                    enabled: !shell.offlineMode && !listenbrainz.importing
                             && (historyUser.text.length > 0 || (historySource.currentIndex === 0 && listenbrainz.connected))
                    onClicked: listenbrainz.importHistory(historySource.currentIndex === 0 ? "listenbrainz" : "lastfm", historyUser.text)
                }
            }
            Text {
                textFormat: Text.PlainText
                visible: listenbrainz.importStatus.length > 0
                width: parent.width
                text: listenbrainz.importStatus
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13); wrapMode: Text.WordWrap
            }
            Text { text: "Discord Rich Presence"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(15); font.weight: Font.DemiBold; textFormat: Text.PlainText }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Show what you're listening to on your Discord profile. Create an application at discord.com/developers, paste its Application ID below and upload your icon as an art asset named “hallucinate”. Status: " + discord.status
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
            }
            StyledCheck { text: "Enable Discord Rich Presence"; checked: discord.enabled; onToggled: discord.setEnabled(checked) }
            TextField {
                width: 320
                placeholderText: "Discord application ID"
                text: discord.appId
                selectByMouse: true
                color: Theme.text
                placeholderTextColor: Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14)
                background: Rectangle { radius: Theme.radiusSmall; color: Theme.surface; border.color: parent.activeFocus ? Theme.accent : Theme.border }
                onEditingFinished: discord.setAppId(text)
            }
            StyledCheck { text: "Hide when paused"; checked: discord.hidePaused; onToggled: discord.setPref("hidePaused", checked) }
            StyledCheck { text: "Hide cover art"; checked: discord.hideCover; onToggled: discord.setPref("hideCover", checked) }
            StyledCheck { text: "Privacy mode (don't share track details)"; checked: discord.privacy; onToggled: discord.setPref("privacy", checked) }

        }
        SettingsSection {
            id: sec_desktop
            objectName: "settings_desktop"
            title: "Desktop"
            keywords: "tray notifications close quit minimize exit background mini player"
            query: page.query
            StyledCheck {
                visible: shell.trayAvailable
                text: "Show system tray icon"
                checked: shell.trayEnabled
                onToggled: shell.setTrayEnabled(checked)
            }
            Row {
                spacing: 12
                Text { anchors.verticalCenter: parent.verticalCenter; text: "When I close the window"; color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); textFormat: Text.PlainText }
                StyledCombo {
                    objectName: "closeAction"
                    width: 250
                    readonly property var actions: ["ask", "quit"].concat(shell.canMinimize ? ["minimize"] : [])
                                                                  .concat(shell.trayAvailable ? ["tray"] : [])
                    readonly property var labels: ({ ask: "Ask every time", quit: "Quit", minimize: "Minimize",
                                                     tray: "Keep playing in the tray" })
                    model: actions.map(a => labels[a])
                    currentIndex: Math.max(0, actions.indexOf(shell.closeAction))
                    onActivated: shell.setCloseAction(actions[currentIndex])
                }
            }
            Text {
                textFormat: Text.PlainText
                visible: !shell.canMinimize
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Your window manager has no minimize, so the choices are quitting or keeping it in the tray (when your bar shows tray icons)."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            StyledCheck {
                visible: Qt.platform.os === "linux" || shell.trayAvailable
                text: "Show desktop notifications when tracks change"
                checked: shell.desktopNotifications
                onToggled: shell.setDesktopNotifications(checked)
            }
            PillButton { text: "Open mini player"; onClicked: shell.toggleMini() }

        }
        SettingsSection {
            id: sec_about
            objectName: "settings_about"
            title: "About"
            keywords: "version debug bug report update check logo"
            query: page.query
            Image {
                width: 260
                height: 210
                source: "../assets/logo.png"
                fillMode: Image.PreserveAspectFit
                sourceSize: Qt.size(600, 600)
                smooth: true
                Accessible.name: "Hallucinate logo"
            }
            Text {
                textFormat: Text.PlainText
                text: "Hallucinate " + shell.appVersion + " — a modern music library and player"
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Row {
                spacing: 10
                PillButton {
                    objectName: "copyDebugInfo"
                    text: "Copy debug info"
                    onClicked: { shell.copyDebugInfo(); Nav.notify("Debug info copied — paste it into your bug report") }
                }
                PillButton {
                    text: "Report a bug"
                    onClicked: Qt.openUrlExternally("https://github.com/Phosphene-dev/Hallucinate/issues/new")
                }
            }
            Text {
                textFormat: Text.PlainText
                visible: !shell.updates.supported
                text: "Updates come through your software centre or package manager."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
            }
            Row {
                visible: shell.updates.supported
                spacing: 12
                StyledCheck {
                    objectName: "updateChecks"
                    text: "Tell me when a new version is out (checks GitHub once a day)"
                    checked: shell.updates.enabled
                    onToggled: shell.updates.setEnabled(checked)
                }
                PillButton {
                    anchors.verticalCenter: parent.verticalCenter
                    height: 32
                    text: shell.updates.busy ? "Checking…" : "Check now"
                    enabled: !shell.updates.busy && !shell.offlineMode
                    onClicked: shell.updates.checkNow()
                }
                PillButton {
                    objectName: "updateNow"
                    anchors.verticalCenter: parent.verticalCenter
                    height: 32
                    primary: true
                    visible: shell.updates.canInstall && (shell.updates.available || shell.updates.installing)
                    text: shell.updates.installing ? "Cancel" : "Update now"
                    enabled: shell.updates.installing || !shell.offlineMode
                    onClicked: shell.updates.installing ? shell.updates.cancelInstall() : Nav.installUpdate()
                }
            }
            Text {
                textFormat: Text.PlainText
                visible: shell.updates.status.length > 0
                text: shell.updates.status
                color: shell.updates.available ? Theme.accent : Theme.textDim
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
                MouseArea {
                    anchors.fill: parent
                    enabled: shell.updates.available
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Qt.openUrlExternally(shell.updates.releaseUrl)
                }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: "Debug info lists versions, your system, display and audio setup and the recent log. It leaves out "
                    + "file paths, your music and account names."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(12)
            }
        }
    }
    }
}
