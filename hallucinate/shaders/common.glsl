// Shared by the visualizer shaders; scripts/build_shaders.py pastes it into each one that includes it.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;      // seconds, slowed or sped up by the music's energy
    float bass;      // smoothed band energies, 0..1
    float mid;
    float treble;
    float energy;
    float beat;      // jumps to 1 on a kick, then decays
    vec2 res;        // pixel size, for aspect
    vec4 c0;         // the cover's colours
    vec4 c1;
    vec4 c2;
    vec4 s0; vec4 s1; vec4 s2; vec4 s3; vec4 s4; vec4 s5;  // 24 spectrum bands, low to high
};

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}

float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    mat2 r = mat2(0.8, 0.6, -0.6, 0.8);
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = r * p * 2.02 + 17.0;
        a *= 0.5;
    }
    return v;
}

float band(float x) {
    float i = clamp(x, 0.0, 1.0) * 23.0;
    int lo = int(floor(i));
    float f = fract(i);
    float b[24] = float[24](s0.x, s0.y, s0.z, s0.w, s1.x, s1.y, s1.z, s1.w, s2.x, s2.y, s2.z, s2.w,
                            s3.x, s3.y, s3.z, s3.w, s4.x, s4.y, s4.z, s4.w, s5.x, s5.y, s5.z, s5.w);
    return mix(b[lo], b[min(lo + 1, 23)], f);
}

// Cover colours are often muted; push them to full brightness and a bit more saturation so the light glows
vec3 vivid(vec4 c) {
    vec3 v = c.rgb / max(max(c.r, max(c.g, c.b)), 0.08);
    float l = dot(v, vec3(0.299, 0.587, 0.114));
    return clamp(mix(vec3(l), v, 1.45), 0.0, 1.0);
}

// Round, randomly placed stars on a grid of `cell` pixels; `density` is the share of cells holding one
float stars(vec2 px, float cell, float density, float twinkle) {
    vec2 g = floor(px / cell);
    float h = hash(g);
    if (h > density) return 0.0;
    vec2 centre = (g + 0.2 + 0.6 * vec2(hash(g + 7.1), hash(g + 3.7))) * cell;
    float size = 0.6 + 1.1 * hash(g + 1.3);
    float glow = exp(-dot(px - centre, px - centre) / (size * size));
    return glow * (1.0 - twinkle + twinkle * (0.5 + 0.5 * sin(time * 2.5 + h * 60.0)));
}

vec2 aspectUv() {
    vec2 uv = qt_TexCoord0 - 0.5;
    uv.x *= res.x / max(res.y, 1.0);
    return uv;
}

vec3 finish(vec3 col) {
    vec2 v = qt_TexCoord0 - 0.5;
    col *= 1.0 - 0.55 * dot(v, v) * 1.6;                       // soft vignette
    col += (hash(qt_TexCoord0 * res + fract(time)) - 0.5) * 0.025;  // a little grain against banding
    return col;
}
