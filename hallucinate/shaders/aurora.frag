#version 440
#include "common.glsl"

// Curtains of light over a night sky; each part of a curtain rises with its part of the spectrum.
void main() {
    vec3 a = vivid(c0), b = vivid(c1), c = vivid(c2);
    vec2 uv = qt_TexCoord0;   // y grows downwards
    vec2 p = aspectUv();
    vec3 col = mix(a * 0.03, b * 0.07, uv.y);
    col += stars(uv * res, 9.0, 0.06, 0.6 + 0.4 * treble) * (0.6 + 0.6 * treble) * smoothstep(1.0, 0.3, uv.y);

    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float x = p.x * (1.1 + 0.35 * fi) + fi * 3.1;
        float bx = uv.x * 0.8 + 0.06 * fi;
        float lift = (band(bx - 0.05) + 2.0 * band(bx) + band(bx + 0.05)) * 0.25;
        float edge = 0.5 + 0.09 * fi - 0.2 * lift - 0.1 * bass
                   + 0.09 * sin(x * 1.6 + time * (0.3 + 0.1 * fi))
                   + 0.12 * (fbm(vec2(x * 0.7, time * 0.08 + fi * 4.0)) - 0.5);
        float d = edge - uv.y;                                    // > 0 above the curtain's lower edge
        float body = smoothstep(-0.012, 0.012, d) * exp(-max(d, 0.0) * (3.2 + fi));
        float rays = pow(fbm(vec2(x * 9.0, time * 0.3 + fi * 9.0)), 1.6) * 1.8;
        float hem = exp(-abs(d) * 60.0);                         // the bright lower fringe
        vec3 tint = mix(i == 1 ? b : a, c, smoothstep(0.0, 0.3, d));
        float power = (0.55 + 0.7 * lift + 0.35 * beat) * (1.0 - 0.22 * fi);
        col += tint * (body * rays * 0.9 + hem * 0.6) * power;
    }
    col += b * 0.1 * smoothstep(0.7, 1.0, uv.y) * (0.5 + energy);   // glow along the horizon
    fragColor = vec4(finish(col), 1.0) * qt_Opacity;
}
