# 데모영상용 배경음악: 저작권 문제가 없도록 코드로 직접 합성한 오리지널 곡 (90 BPM, 잔잔한 앰비언트 팝)
import numpy as np, wave
SR = 44100; BPM = 92; beat = 60 / BPM; DUR = 82.0
N = int(SR * DUR); rng = np.random.default_rng(7)
t_all = np.arange(N) / SR
def midi(n): return 440 * 2 ** ((n - 69) / 12)
# 진행: Cmaj7 - Am7 - Fmaj7 - G6sus (2마디씩), 부드러운 보이싱
prog = [[48, 55, 59, 64, 67], [45, 52, 55, 60, 64], [41, 48, 52, 57, 64], [43, 50, 55, 59, 62]]
bar = 4 * beat
L = np.zeros(N); R = np.zeros(N)
def add(sig, start, pan=0.0, gain=1.0):
    i = int(start * SR); j = min(N, i + len(sig))
    if i >= N: return
    s = sig[: j - i] * gain
    L[i:j] += s * (1 - pan) ** .5; R[i:j] += s * (1 + pan) ** .5
def pad(freqs, dur):
    n = int(dur * SR); t = np.arange(n) / SR; s = np.zeros(n)
    for f in freqs:
        for h, a in [(1, 1), (2, .25), (3, .08)]:
            det = 1 + rng.uniform(-.003, .003)
            s += a * np.sin(2 * np.pi * f * h * det * t + rng.uniform(0, 6.28))
    env = np.minimum(1, t / 1.2) * np.minimum(1, (dur - t) / 1.0).clip(0)
    lfo = 1 + .08 * np.sin(2 * np.pi * .25 * t)
    return s * env * lfo / len(freqs)
def pluck(f, dur=1.6):
    n = int(dur * SR); p = int(SR / f); buf = rng.uniform(-1, 1, p); out = np.zeros(n)
    for k in range(n):
        out[k] = buf[k % p]; buf[k % p] = .5 * (buf[k % p] + buf[(k + 1) % p]) * .996
    return out * np.exp(-np.arange(n) / SR * 2.2)
def kick():
    n = int(.35 * SR); t = np.arange(n) / SR
    return np.sin(2 * np.pi * (50 + 70 * np.exp(-t * 30)) * t) * np.exp(-t * 9)
def hat():
    n = int(.06 * SR); s = rng.normal(0, 1, n); s = np.diff(np.concatenate([[0], s])); return s * np.exp(-np.arange(n) / SR * 70)
nbars = int(DUR / bar) + 1
plk_cache = {}
for b in range(nbars):
    ch = prog[(b // 2) % 4]; t0 = b * bar
    if b % 2 == 0: add(pad([midi(n) for n in ch], 2 * bar + .8), t0, 0, .55)
    tb = np.arange(int(bar * SR)) / SR; add(np.sin(2 * np.pi * midi(ch[0] - 12) * tb) * np.minimum(1, tb / .04) * np.exp(-tb * .9), t0, 0, .35)  # 베이스
    if b >= 2:  # 아르페지오
        pat = [ch[1] + 12, ch[2] + 12, ch[3] + 12, ch[4] + 12, ch[3] + 12, ch[2] + 12, ch[4] + 12, ch[3] + 24 - 12]
        for k, n in enumerate(pat):
            if n not in plk_cache: plk_cache[n] = pluck(midi(n))
            add(plk_cache[n], t0 + k * beat / 2, pan=(-.35 if k % 2 else .35), gain=.22 * (1 if k % 4 == 0 else .7))
    if 4 <= b < nbars - 2:  # 리듬
        for k in range(4):
            if k in (0, 2): add(kick(), t0 + k * beat, 0, .5)
            add(hat(), t0 + k * beat + beat / 2, .2, .07)
# 간단한 잔향
ir = rng.normal(0, 1, int(1.8 * SR)) * np.exp(-np.arange(int(1.8 * SR)) / SR * 3.2) * .012
from numpy.fft import rfft, irfft
def conv(x):
    n = len(x) + len(ir); m = 1 << (n - 1).bit_length(); return irfft(rfft(x, m) * rfft(ir, m), m)[: len(x)]
L = L + conv(L) * .9; R = R + conv(R) * .9
fade = np.minimum(1, t_all / 2.5) * np.minimum(1, (DUR - t_all) / 4.0).clip(0)
L *= fade; R *= fade
rms = np.sqrt((L**2 + R**2).mean() / 2); L /= rms * 6; R /= rms * 6
L = np.tanh(1.6 * L) / np.tanh(1.6); R = np.tanh(1.6 * R) / np.tanh(1.6)
peak = max(abs(L).max(), abs(R).max()); L *= .85 / peak; R *= .85 / peak
data = (np.stack([L, R], 1) * 32767).astype(np.int16)
with wave.open("bgm.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(data.tobytes())
print("ok")
