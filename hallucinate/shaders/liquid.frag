#version 440
#include "common.glsl"

// Slow, domain-warped colour flowing like ink in water; the bass pushes the flow, beats swell it.
void main() {
    vec3 a = vivid(c0), b = vivid(c1), c = vivid(c2);
    vec2 uv = aspectUv() * (2.2 - 0.25 * bass);
    float t = time * 0.07;
    vec2 q = vec2(fbm(uv + vec2(0.0, t)), fbm(uv + vec2(5.2, 1.3) - t));
    vec2 r = vec2(fbm(uv + 3.6 * q + vec2(1.7, 9.2) + 0.15 * t + bass * 0.6),
                  fbm(uv + 3.6 * q + vec2(8.3, 2.8) - 0.12 * t));
    float f = fbm(uv + 3.2 * r);

    vec3 col = mix(a * 0.08, a * 0.75, smoothstep(0.2, 0.8, f));
    col = mix(col, b * 0.85, smoothstep(0.35, 1.05, length(q)) * 0.8);
    col = mix(col, c, smoothstep(0.6, 0.95, r.y) * (0.5 + 0.5 * mid));
    col *= 0.35 + 1.1 * f * f + 0.3 * energy + 0.25 * beat;
    col += mix(b, vec3(1.0), 0.35) * pow(max(f - 0.55, 0.0) * 2.4, 3.0) * (0.5 + treble);  // light on the crests
    fragColor = vec4(finish(col), 1.0) * qt_Opacity;
}
