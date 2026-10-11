import QtQuick
import "."

Canvas {
    id: c
    property string name: ""
    property bool filled: false
    property color color: Theme.text
    implicitWidth: 20
    implicitHeight: 20
    onNameChanged: requestPaint()
    onFilledChanged: requestPaint()
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
        case "radio":  // broadcast waves around a dot
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.09, 0, 2*Math.PI); ctx.fill()
            for (var r = 1; r <= 2; r++) {
                ctx.beginPath(); ctx.arc(w*.5, h*.5, w*(.12 + .17*r), -Math.PI/4, Math.PI/4); ctx.stroke()
                ctx.beginPath(); ctx.arc(w*.5, h*.5, w*(.12 + .17*r), Math.PI*3/4, Math.PI*5/4); ctx.stroke()
            }
            break
        case "expand": line([.15,.55,.15,.15,.55,.15]); line([.85,.45,.85,.85,.45,.85]); line([.15,.15,.45,.45]); line([.85,.85,.55,.55]); break
        case "queue": line([.1,.25,.9,.25]); line([.1,.5,.9,.5]); line([.1,.75,.55,.75]); break
        case "volume":
            ctx.beginPath(); ctx.moveTo(w*.1,h*.38); ctx.lineTo(w*.3,h*.38); ctx.lineTo(w*.52,h*.18); ctx.lineTo(w*.52,h*.82); ctx.lineTo(w*.3,h*.62); ctx.lineTo(w*.1,h*.62); ctx.closePath(); ctx.fill()
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.3, -0.9, 0.9); ctx.stroke(); break
        case "plus": line([.5,.18,.5,.82]); line([.18,.5,.82,.5]); break
        case "heart":
            ctx.beginPath()
            ctx.moveTo(w*.5, h*.86)
            ctx.bezierCurveTo(w*.05, h*.55, w*.05, h*.18, w*.28, h*.18)
            ctx.bezierCurveTo(w*.42, h*.18, w*.5, h*.3, w*.5, h*.3)
            ctx.bezierCurveTo(w*.5, h*.3, w*.58, h*.18, w*.72, h*.18)
            ctx.bezierCurveTo(w*.95, h*.18, w*.95, h*.55, w*.5, h*.86)
            ctx.closePath()
            if (filled) ctx.fill(); else ctx.stroke()
            break
        case "more":
            for (var k = 0; k < 3; k++) { ctx.beginPath(); ctx.arc(w*(.2 + .3*k), h*.5, w*.075, 0, Math.PI*2); ctx.fill() }
            break
        case "note":
            ctx.beginPath(); ctx.arc(w*.3, h*.75, w*.14, 0, Math.PI*2); ctx.fill(); line([.44,.75,.44,.15,.8,.25])
            break
        case "close": line([.22,.22,.78,.78]); line([.78,.22,.22,.78]); break
        case "back": line([.62,.15,.3,.5,.62,.85]); break
        case "home":
            line([.12,.48,.5,.14,.88,.48]); line([.22,.4,.22,.86,.78,.86,.78,.4]); line([.42,.86,.42,.62,.58,.62,.58,.86]); break
        case "album":  // a record
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.38, 0, Math.PI*2); ctx.stroke()
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.1, 0, Math.PI*2); ctx.fill()
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.24, -0.6, 0.4); ctx.stroke(); break
        case "artist":
            ctx.beginPath(); ctx.arc(w*.5, h*.34, w*.17, 0, Math.PI*2); ctx.stroke()
            ctx.beginPath(); ctx.arc(w*.5, h*.98, w*.34, Math.PI*1.12, Math.PI*1.88); ctx.stroke(); break
        case "songs":
            line([.1,.24,.56,.24]); line([.1,.46,.56,.46]); line([.1,.68,.4,.68])
            ctx.beginPath(); ctx.arc(w*.68, h*.76, w*.1, 0, Math.PI*2); ctx.fill(); line([.78,.76,.78,.2,.92,.26]); break
        case "stats":
            ctx.fillRect(w*.14, h*.52, w*.16, h*.34); ctx.fillRect(w*.42, h*.18, w*.16, h*.68); ctx.fillRect(w*.7, h*.38, w*.16, h*.48); break
        case "wave":  // the logo's waveform bars
            var bars = [.2, .45, .75, .4, .9, .55, .3]
            for (var b = 0; b < bars.length; b++) {
                var bx = w * (.12 + b * .127), bh = h * bars[b]
                ctx.fillRect(bx, (h - bh) / 2, Math.max(1.5, w * .07), bh)
            }
            break
        case "settings":
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.14, 0, Math.PI*2); ctx.stroke()
            for (var g = 0; g < 8; g++) {
                var a = g * Math.PI / 4
                line([.5 + .26*Math.cos(a), .5 + .26*Math.sin(a), .5 + .4*Math.cos(a), .5 + .4*Math.sin(a)])
            }
            ctx.beginPath(); ctx.arc(w*.5, h*.5, w*.27, 0, Math.PI*2); ctx.stroke(); break
        case "playlist":
            line([.1,.24,.62,.24]); line([.1,.46,.62,.46]); line([.1,.68,.42,.68]); tri(w*.6,h*.56,w*.6,h*.88,w*.9,h*.72); break
        case "sidebar":
            ctx.strokeRect(w*.12, h*.18, w*.76, h*.64); line([.38,.18,.38,.82]); break
        case "sparkle":
            ctx.beginPath(); ctx.moveTo(w*.5,h*.08); ctx.quadraticCurveTo(w*.56,h*.44,w*.92,h*.5); ctx.quadraticCurveTo(w*.56,h*.56,w*.5,h*.92)
            ctx.quadraticCurveTo(w*.44,h*.56,w*.08,h*.5); ctx.quadraticCurveTo(w*.44,h*.44,w*.5,h*.08); ctx.closePath(); ctx.fill(); break
        case "dice":
            ctx.strokeRect(w*.16, h*.16, w*.68, h*.68)
            var pips = [[.34,.34],[.66,.66],[.5,.5],[.66,.34],[.34,.66]]
            for (var q = 0; q < pips.length; q++) { ctx.beginPath(); ctx.arc(w*pips[q][0], h*pips[q][1], w*.06, 0, Math.PI*2); ctx.fill() }
            break
        case "search":
            ctx.beginPath(); ctx.arc(w*.42, h*.42, w*.28, 0, Math.PI*2); ctx.stroke(); line([.64,.64,.9,.9]); break
        }
    }
}
