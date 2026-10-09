import QtQuick
import QtQuick.Controls
import "."

Item {
    id: page
    objectName: "settings"

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: settingsColumn.implicitHeight + 40
        clip: true
        boundsBehavior: Flickable.StopAtBounds

    Column {
        id: settingsColumn
        x: 28; y: 20
        width: page.width - 56
        spacing: 16

        Text { text: "Settings"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(30); font.weight: Font.Bold }
        Text { text: "Appearance"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(20); font.weight: Font.DemiBold }
        Row {
            spacing: 12
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Theme"
                color: Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize(14)
            }
            ComboBox {
                id: themePicker
                objectName: "themePicker"
                width: 260
                model: themeManager.availableThemes
                currentIndex: Math.max(0, themeManager.availableThemes.indexOf(themeManager.currentTheme))
                onActivated: themeManager.selectTheme(currentText)
                contentItem: Text {
                    objectName: "themePickerText"
                    leftPadding: 12
                    rightPadding: 28
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
        CheckBox {
            id: albumAccentToggle
            text: "Use album-art accent color"
            checked: themeManager.albumArtAccent
            onToggled: themeManager.setAlbumArtAccent(checked)
            contentItem: Text {
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
                    anchors.centerIn: parent
                    text: albumAccentToggle.checked ? "✓" : ""
                    color: Theme.onAccent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSize(13)
                }
            }
        }
        Text {
            text: "Custom themes: " + themeManager.userThemeDirectory + "/*.json"
            color: Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(12)
        }
        PillButton {
            text: "Reload themes"
            onClicked: themeManager.reloadThemes()
        }

        Text { text: "Music folders"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(20); font.weight: Font.DemiBold }
        Text {
            text: "Folders are scanned in the background and watched for changes."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
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
                    color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(14); elide: Text.ElideMiddle
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
        }
        ScanBar { width: parent.width }
        Text {
            visible: !library.scanning && library.status.length > 0
            text: library.status
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
        }
        Text {
            width: parent.width
            visible: library.missingFolders.length > 0
            wrapMode: Text.WordWrap
            text: "Folder not found or unreadable: " + library.missingFolders.join(", ")
            color: Theme.error; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
        }
        Text {
            visible: library.unreadableFiles > 0 && !library.scanning
            text: library.unreadableFiles + " files could not be read and were skipped."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
        }
        PillButton { text: "Choose folder…"; onClicked: picker.open() }
        FolderPicker { id: picker }

        Rectangle { width: parent.width; height: 1; color: Theme.border }
        Text { text: "Last.fm"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(20); font.weight: Font.DemiBold }
        Text {
            width: parent.width
            wrapMode: Text.WordWrap
            text: "Connect your Last.fm account to send now-playing updates and scrobbles after listening to half a track or four minutes, whichever comes first. API credentials are stored in the system keyring."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize(13)
        }
        Text {
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
                enabled: scrobbler.configured && !scrobbler.busy
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
            width: parent.width
            text: scrobbler.status + (scrobbler.pendingCount > 0 ? " · " + scrobbler.pendingCount + " queued scrobbles" : "")
            color: scrobbler.connected ? Theme.accent : Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize(13)
            wrapMode: Text.WordWrap
        }
    }
    }
}
