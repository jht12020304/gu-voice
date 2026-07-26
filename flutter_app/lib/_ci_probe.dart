// 刻意的 lint，用來驗證 CI 的 flutter-checks 會攔下來（下一個 commit 移除）
void probeCiCatchesLint(void Function(int, int) g) => g(1, 2);
void probeCallsite() => probeCiCatchesLint((_, __) {});
