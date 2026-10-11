#version 440
#include "common.glsl"

// A slowly turning cloud of gas and stars; the core breathes with the bass and flares on beats.
void main() {
    vec3 a = vivid(c0), b = vivid(c1), c = vivid(c2);
    vec2 p = aspectUv() * 2.2;
    float r = length(p);
    float ang = atan(p.y, p.x);
    float swirl = ang + 1.6 / (r + 0.35) - time * 0.05;
    vec2 sp = vec2(cos(swirl), sin(swirl)) * r;

    float d = fbm(sp * 1.6 + vec2(time * 0.03, 0.0));
    float d2 = fbm(sp * 3.2 - d * 1.5 + time * 0.02);
    float core = exp(-r * (2.2 - 0.9 * bass - 0.4 * beat));
    float gas = smoothstep(0.35, 0.95, d * (0.7 + d2)) * exp(-r * 0.55);

    vec3 col = a * gas * (0.7 + 0.5 * mid);
    col = mix(col, b * (gas + 0.2), smoothstep(0.45, 0.9, d2) * 0.7);
    col += c * core * (0.8 + 0.8 * energy);
    col += vec3(1.0) * pow(core, 3.0) * 0.35 * (0.5 + beat);

    // stars, twinkling with the treble
    col += stars(qt_TexCoord0 * res, 8.0, 0.07, 0.3 + 0.7 * treble) * (1.0 - 0.8 * gas) * 0.9;
    col += b * 0.03;
    fragColor = vec4(finish(col), 1.0) * qt_Opacity;
}
