export function quantizeVolume(value: number): number {
    const clamped = Math.max(0, Math.min(1, value));
    return Math.round(clamped * 100) / 100;
}

export function shouldEmitVolume(
    nowMs: number,
    lastEmitMs: number,
    nextValue: number,
    lastValue: number,
    force: boolean = false,
): boolean {
    if (force) return true;
    const elapsed = nowMs - lastEmitMs;
    const delta = Math.abs(nextValue - lastValue);
    return !(elapsed < 66 && delta < 0.02);
}
