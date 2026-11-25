import QtQuick
import QtMultimedia

Item {
    id: root
    objectName: "videoRoot"
    property color backgroundColor: "#0D0D0D"

    Rectangle {
        anchors.fill: parent
        color: root.backgroundColor
    }

    VideoOutput {
        id: videoOutput
        objectName: "videoOutput"
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectFit
    }

    Image {
        id: frameImage
        objectName: "frameImage"
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        visible: false
        cache: false
        asynchronous: false
        smooth: true
    }
}
