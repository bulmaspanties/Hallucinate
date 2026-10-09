import QtQuick
import "."

Canvas {
    id: c
    property string name: ""
    property color color: Theme.text
    implicitWidth: 20
    implicitHeight: 20
    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var w = width, h = height
        ctx.fillStyle = color
        ctx.strokeStyle = color
        ctx.lineWidth = Math.max(1.6, w / 11)
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        function tri(a, b, c2, d, e, f) {
            ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c2, d); ctx.lineTo(e, f); ctx.closePath(); ctx.fill()
        }
        function line(pts) {
            ctx.beginPath(); ctx.moveTo(pts[0] * w, pts[1] * h)
            for (var i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i] * w, pts[i + 1] * h)
            ctx.stroke()
        }
        switch (name) {
        case "play": tri(w*.25, h*.12, w*.25, h*.88, w*.88, h*.5); break
        case "pause": ctx.fillRect(w*.2, h*.14, w*.2, h*.72); ctx.fillRect(w*.6, h*.14, w*.2, h*.72); break
        case "next": tri(w*.12, h*.2, w*.12, h*.8, w*.66, h*.5); ctx.fillRect(w*.72, h*.2, w*.14, h*.6); break
        case "prev": tri(w*.88, h*.2, w*.88, h*.8, w*.34, h*.5); ctx.fillRect(w*.14, h*.2, w*.14, h*.6); break
        case "shuffle":
            line([.08,.3,.38,.3,.62,.7,.8,.7]); line([.08,.7,.38,.7,.62,.3,.8,.3])
            tri(w*.78,h*.18,w*.96,h*.3,w*.78,h*.42); tri(w*.78,h*.58,w*.96,h*.7,w*.78,h*.82); break
        case "repeat": case "repeat1":
            line([.15,.5,.15,.3,.78,.3]); tri(w*.74,h*.14,w*.96,h*.3,w*.74,h*.46)
            line([.85,.5,.85,.7,.22,.7]); tri(w*.26,h*.54,w*.04,h*.7,w*.26,h*.86)
            if (name === "repeat1") { ctx.font = "bold " + Math.round(h*.45) + "px sans-serif"; ctx.textAlign = "center"; ctx.fillText("1", w*.5, h*.62) }
            break
        case "queue": line([.1,.25,.9,.25]); line([.1,.5,.9,.5]); line([.1,.75,.55,.75]); break
        case "volume":
            ctx.beginPath(); ctx.moveTo(w*.1,h*.38); ctx.lineTo(w*.3,h*.38); ctx.lineTo(w*.52,h*.18); ctx.lineTo(w*.52,h*.82); ctx.lineTo(w*.3,h*.62); ctx.lineTo(w*.1,h*.62); ctx.closePath(); ctx.fill()
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.3, -0.9, 0.9); ctx.stroke(); break
        case "plus": line([.5,.18,.5,.82]); line([.18,.5,.82,.5]); break
        case "close": line([.22,.22,.78,.78]); line([.78,.22,.22,.78]); break
        case "back": line([.62,.15,.3,.5,.62,.85]); break
        case "search":
            ctx.beginPath(); ctx.arc(w*.42, h*.42, w*.28, 0, Math.PI*2); ctx.stroke(); line([.64,.64,.9,.9]); break
        }
    }
}
